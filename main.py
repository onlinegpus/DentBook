from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from uuid import uuid4, UUID
import datetime
import sqlite3
import random
# --- App Configuration ---
app = FastAPI(
    title="Task Management API",
    description="A simple REST API built with FastAPI to manage tasks.",
    version="1.0.0"
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (for development)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# --- Data Models (Pydantic) ---

class Doctor(BaseModel):
    id: str = None
    student_id: str  # Unique ID for login/search
    username: str
    password: str
    color: str = "#3b82f6" # Default color, changeable later
    matches: List[str] = [] # List of doctor IDs this user is connected to
    phone: Optional[str] = None
    country_code: Optional[str] = None

class LoginRequest(BaseModel):
    student_id: str
    password: str

class MatchRequest(BaseModel):
    id: str = None
    from_id: str
    from_name: str
    to_student_id: str # We search by Student ID

class Patient(BaseModel):
    id: str = None
    doctor_id: str
    name: str
    r4: Optional[str] = None

class Appointment(BaseModel):
    id: str = None
    doctor_id: str
    day: str  # Sun, Mon, Tue, Wed, Thu
    session: str  # "Morning" or "Afternoon"
    patient_name: str
    patient_r4: str
    duration: str
    type: str
    other_type_details: Optional[str] = None
    rank: int = 0

class ColorUpdate(BaseModel):
    color: str

class BlockedDay(BaseModel):
    doctor_id: str
    day: str

class ReorderRequest(BaseModel):
    ids: List[str]

class MoveRequest(BaseModel):
    day: str
    session: str

class GlobalBlock(BaseModel):
    doctor_id: str
    day_of_week: str # Sun, Mon, Tue, Wed, Thu
    session: str # Morning, Afternoon

# --- Database Setup (SQLite) ---
DB_FILE = "dentbook.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS doctors (
            id TEXT PRIMARY KEY,
            student_id TEXT UNIQUE,
            username TEXT,
            password TEXT,
            color TEXT
        )""")
        # Migration for new fields
        try:
            conn.execute("ALTER TABLE doctors ADD COLUMN phone TEXT")
            conn.execute("ALTER TABLE doctors ADD COLUMN country_code TEXT")
        except sqlite3.OperationalError:
            pass

        conn.execute("""CREATE TABLE IF NOT EXISTS matches (
            doctor_id TEXT,
            target_id TEXT,
            PRIMARY KEY (doctor_id, target_id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS match_requests (
            id TEXT PRIMARY KEY,
            from_id TEXT,
            from_name TEXT,
            to_student_id TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            doctor_id TEXT,
            name TEXT,
            r4 TEXT -- Nullable now
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            doctor_id TEXT,
            day TEXT,
            session TEXT,
            patient_name TEXT,
            patient_r4 TEXT,
            duration TEXT,
            type TEXT,
            other_type_details TEXT,
            rank INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS blocked_days (
            doctor_id TEXT,
            day TEXT,
            PRIMARY KEY (doctor_id, day)
        )""")
        
        # Migration: Ensure rank column exists (for existing DBs)
        try:
            conn.execute("ALTER TABLE appointments ADD COLUMN rank INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass 
        
        conn.execute("""CREATE TABLE IF NOT EXISTS global_blocks (
            doctor_id TEXT,
            day_of_week TEXT,
            session TEXT,
            PRIMARY KEY (doctor_id, day_of_week, session)
        )""")

init_db()

def get_matches_list(doctor_id: str) -> List[str]:
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT target_id FROM matches WHERE doctor_id = ?", (doctor_id,)).fetchall()
        return [r[0] for r in rows]

def get_random_color():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

# --- API Endpoints ---

@app.get("/", tags=["Root"])
async def read_root():
    return FileResponse("index.html")

@app.get("/index.html", tags=["UI"])
async def read_index():
    return FileResponse("index.html")

@app.get("/admin.html", tags=["UI"])
async def read_admin():
    return FileResponse("admin.html")

# --- Auth & Users ---

# Note: We use 'r4' in the database schema for the patient ID, 
# but the frontend displays it as "R5" as requested.

@app.post("/register", status_code=201)
async def register(doctor: Doctor):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Check if exists
        existing = cursor.execute("SELECT 1 FROM doctors WHERE student_id = ?", (doctor.student_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Student ID already exists")
        
        doctor.id = str(uuid4())
        doctor.color = get_random_color() # Assign random color
        cursor.execute("INSERT INTO doctors (id, student_id, username, password, color, phone, country_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (doctor.id, doctor.student_id, doctor.username, doctor.password, doctor.color, doctor.phone, doctor.country_code))
        conn.commit()
        return doctor

@app.post("/login")
async def login(creds: LoginRequest):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM doctors WHERE student_id = ? AND password = ?", 
                           (creds.student_id, creds.password)).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        doc = dict(row)
        doc['matches'] = get_matches_list(doc['id'])
        return doc

@app.get("/doctors/me")
async def get_me(id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doctor not found")
        doc = dict(row)
        doc['matches'] = get_matches_list(id)
        return doc

@app.get("/doctors")
async def search_doctors(student_id: str = ""):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM doctors WHERE student_id LIKE ?", (f"%{student_id}%",)).fetchall()
        return [dict(r) for r in rows]

@app.get("/doctors/batch")
async def get_doctors_batch(ids: str = Query(...)):
    id_list = ids.split(",")
    if not id_list: return []
    placeholders = ','.join('?' for _ in id_list)
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM doctors WHERE id IN ({placeholders})", id_list).fetchall()
        return [dict(r) for r in rows]

@app.put("/doctors/{doctor_id}/color")
async def update_color(doctor_id: str, update: ColorUpdate):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE doctors SET color = ? WHERE id = ?", (update.color, doctor_id))
        conn.commit()
    return {"status": "updated"}

# --- Matching ---

@app.post("/match-request")
async def send_match_request(req: MatchRequest):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute("SELECT id FROM doctors WHERE student_id = ?", (req.to_student_id,)).fetchone()
        
        if not target:
            raise HTTPException(status_code=404, detail="Student ID not found")
        if target['id'] == req.from_id:
            raise HTTPException(status_code=400, detail="Cannot match with self")
        
        req.id = str(uuid4())
        conn.execute("INSERT INTO match_requests (id, from_id, from_name, to_student_id) VALUES (?, ?, ?, ?)",
                     (req.id, req.from_id, req.from_name, req.to_student_id))
        conn.commit()
        return {"message": "Request sent"}

@app.get("/match-requests")
async def get_match_requests(to_student_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM match_requests WHERE to_student_id = ?", (to_student_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/match-accept/{req_id}")
async def accept_match(req_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT * FROM match_requests WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404)
        
        # Get target ID (the one who accepted)
        target = conn.execute("SELECT id FROM doctors WHERE student_id = ?", (req['to_student_id'],)).fetchone()
        
        if target:
            # Add bidirectional match
            conn.execute("INSERT OR IGNORE INTO matches (doctor_id, target_id) VALUES (?, ?)", (target['id'], req['from_id']))
            conn.execute("INSERT OR IGNORE INTO matches (doctor_id, target_id) VALUES (?, ?)", (req['from_id'], target['id']))
        
        conn.execute("DELETE FROM match_requests WHERE id = ?", (req_id,))
        conn.commit()
        return {"message": "Matched"}

@app.delete("/matches/{doctor_id}/{target_id}")
async def remove_match(doctor_id: str, target_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM matches WHERE doctor_id = ? AND target_id = ?", (doctor_id, target_id))
        conn.commit()
    return {"status": "removed"}

# --- Patients ---

@app.get("/patients")
async def get_patients(doctor_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM patients WHERE doctor_id = ?", (doctor_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/patients")
async def add_patient(p: Patient):
    p.id = str(uuid4())
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO patients (id, doctor_id, name, r4) VALUES (?, ?, ?, ?)",
                     (p.id, p.doctor_id, p.name, p.r4 or ""))
        conn.commit()
    return p

@app.delete("/patients/{pid}")
async def delete_patient(pid: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM patients WHERE id = ?", (pid,))
        conn.commit()
    return {"status": "deleted"}

# --- Appointments ---

@app.get("/appointments")
async def get_appointments(doctor_ids: str = Query(...)):
    ids = doctor_ids.split(",")
    if not ids: return []
    placeholders = ','.join('?' for _ in ids)
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM appointments WHERE doctor_id IN ({placeholders}) ORDER BY rank ASC", ids).fetchall()
        return [dict(r) for r in rows]

@app.post("/appointments")
async def create_appointment(appt: Appointment):
    appt.id = str(uuid4())
    with sqlite3.connect(DB_FILE) as conn:
        # Get max rank for this slot to append at bottom
        row = conn.execute("SELECT MAX(rank) FROM appointments WHERE doctor_id=? AND day=? AND session=?", 
                           (appt.doctor_id, appt.day, appt.session)).fetchone()
        new_rank = (row[0] if row[0] is not None else 0) + 1

        conn.execute("""INSERT INTO appointments 
            (id, doctor_id, day, session, patient_name, patient_r4, duration, type, other_type_details, rank) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (appt.id, appt.doctor_id, appt.day, appt.session, appt.patient_name, appt.patient_r4, 
             appt.duration, appt.type, appt.other_type_details, new_rank))
        conn.commit()
    return appt

@app.delete("/appointments/{appt_id}")
async def delete_appointment(appt_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
    return {"status": "deleted"}

@app.put("/appointments/reorder")
async def reorder_appointments(req: ReorderRequest):
    with sqlite3.connect(DB_FILE) as conn:
        for index, appt_id in enumerate(req.ids):
            conn.execute("UPDATE appointments SET rank = ? WHERE id = ?", (index, appt_id))
        conn.commit()
    return {"status": "reordered"}

@app.put("/appointments/{appt_id}/move")
async def move_appointment(appt_id: str, req: MoveRequest):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE appointments SET day = ?, session = ? WHERE id = ?", 
                     (req.day, req.session, appt_id))
        conn.commit()
    return {"status": "moved"}

# --- Blocked Days ---

@app.get("/blocked-days")
async def get_blocked_days(doctor_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT day FROM blocked_days WHERE doctor_id = ?", (doctor_id,)).fetchall()
        return [r[0] for r in rows]

@app.post("/blocked-days")
async def toggle_blocked_day(data: BlockedDay):
    with sqlite3.connect(DB_FILE) as conn:
        existing = conn.execute("SELECT 1 FROM blocked_days WHERE doctor_id = ? AND day = ?", 
                                (data.doctor_id, data.day)).fetchone()
        if existing:
            conn.execute("DELETE FROM blocked_days WHERE doctor_id = ? AND day = ?", (data.doctor_id, data.day))
            conn.commit()
            return {"status": "unblocked"}
        else:
            conn.execute("INSERT INTO blocked_days (doctor_id, day) VALUES (?, ?)", (data.doctor_id, data.day))
            conn.commit()
            return {"status": "blocked"}

@app.get("/global-blocks")
async def get_global_blocks(doctor_ids: str = Query(...)):
    ids = doctor_ids.split(",")
    if not ids: return []
    placeholders = ','.join('?' for _ in ids)
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT doctor_id, day_of_week, session FROM global_blocks WHERE doctor_id IN ({placeholders})", ids).fetchall()
        return [dict(r) for r in rows]

@app.post("/global-blocks")
async def toggle_global_block(data: GlobalBlock):
    with sqlite3.connect(DB_FILE) as conn:
        exists = conn.execute("SELECT 1 FROM global_blocks WHERE doctor_id=? AND day_of_week=? AND session=?", 
                              (data.doctor_id, data.day_of_week, data.session)).fetchone()
        if exists:
            conn.execute("DELETE FROM global_blocks WHERE doctor_id=? AND day_of_week=? AND session=?", (data.doctor_id, data.day_of_week, data.session))
        else:
            conn.execute("INSERT INTO global_blocks (doctor_id, day_of_week, session) VALUES (?, ?, ?)", (data.doctor_id, data.day_of_week, data.session))
        conn.commit()
    return {"status": "toggled"}

# --- Development Server Runner ---
# This allows you to run the file directly with Python (e.g., `python main.py`)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)