
import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime, timedelta, date, time
import plotly.express as px
from PIL import Image

# PDF export imports
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.utils import ImageReader
    reportlab_available = True
except ImportError:
    reportlab_available = False

# Page configuration
st.set_page_config(page_title="Bauzeitenplan Generator", layout="wide")
st.title("🛠️ Bauzeitenplan Generator für Systemstände")
st.markdown(""" 
Lade eine Projektdatei hoch (Excel/CSV) mit Spalten:
- **Standtyp** (z.B. "Komplettstand SMART")
- **Fläche (qm)**
- **Halle** (z.B. "Halle 10.2")

Das Dashboard generiert:
1. Gesamtfläche & Gesamtmanstunden
2. Flächenübersichten je Halle und Standtyp
3. Verteilte Manstunden je Aufgabe mit manueller Anpassung
4. Textuellen Ablaufplan
5. Interaktives Gantt-Chart
6. PDF- und CSV-Export
""")


# Sidebar: Project and contacts
projektname = st.sidebar.text_input("Projektname", "MeinProjekt")
storage_dir = "gespeicherte_projekte"
os.makedirs(storage_dir, exist_ok=True)
projektdatei = os.path.join(storage_dir, f"{projektname}.csv")
load_existing = st.sidebar.checkbox("Gespeichertes Projekt laden")
pm_name = st.sidebar.text_input("Projektmanager", "")
tpl_name = st.sidebar.text_input("Techn. Projektleiter", "")
bauleitung_name = st.sidebar.text_input("Bauleitung", "")

# Sidebar: Scheduling window
start_datum = st.sidebar.date_input("Aufbaubeginn", date.today())
window_start = st.sidebar.time_input("Täglicher Beginn", value=time(8, 0))
window_end = st.sidebar.time_input("Täglicher Ende", value=time(19, 0))

# Sidebar: Team sizes and names
st.sidebar.markdown("### 👷 Teamgrößen & Namen")
team1_name = st.sidebar.text_input("Team 1 Name", "Team 1")
team1 = st.sidebar.number_input("Team 1 Mitglieder", value=10, min_value=0)
team2_name = st.sidebar.text_input("Team 2 Name", "Team 2")
team2 = st.sidebar.number_input("Team 2 Mitglieder", value=4, min_value=0)
team3_name = st.sidebar.text_input("Team 3 Name", "Team 3")
team3 = st.sidebar.number_input("Team 3 Mitglieder", value=0, min_value=0)
total_team = team1 + team2 + team3

# Sidebar: Time per stand type
st.sidebar.markdown("### ⏱️ Minuten/m² je Standtyp")
default_werte = {
    "SMART": 30, "TOKIO": 30, "SYDNEY": 30, "TORONTO": 30, "SONDERSTAND": 30
}
zeitwerte = {
    typ: st.sidebar.number_input(label=typ, value=val, min_value=0)
    for typ, val in default_werte.items()
}

# Load or upload project data
df = None
if load_existing and os.path.exists(projektdatei):
    df = pd.read_csv(projektdatei)
else:
    uploaded = st.file_uploader("Projektdatei (Excel/CSV)", type=["csv", "xlsx"])
    if uploaded:
        if uploaded.name.endswith(".xlsx"):
            df = pd.read_excel(uploaded)
        else:
            df = pd.read_csv(uploaded)
        df.to_csv(projektdatei, index=False)

if df is not None:
    # Normalize columns
    df["Standtyp"] = df["Standtyp"].astype(str).str.upper()
    df["Fläche (qm)"] = pd.to_numeric(df["Fläche (qm)"], errors="coerce").fillna(0)
    df["Halle"] = df["Halle"].astype(str)

    # Dashboard Overview
    st.markdown("## 📋 Projektübersicht")
    st.dataframe(df)

    # Area summaries
    df_halle = df.groupby("Halle")["Fläche (qm)"].sum().reset_index().rename(columns={"Fläche (qm)": "qm"})
    df_typ = df.groupby("Standtyp")["Fläche (qm)"].sum().reset_index().rename(columns={"Fläche (qm)": "qm"})
    st.markdown("## 📐 Fläche je Halle")
    st.table(df_halle)
    st.markdown("## 📐 Fläche je Standtyp")
    st.table(df_typ)

    # Compute man-hours
    df["min_pm"] = df["Standtyp"].map(lambda s: next((v for k, v in zeitwerte.items() if k in s), 0))
    df["man_min"] = df["Fläche (qm)"] * df["min_pm"]
    total_h = df["man_min"].sum() / 60
    st.markdown(f"**Gesamtmanstunden:** {total_h:.1f} h")

    # Distribution sliders
    anteile = {
        "Einmessen": 2, "Traversen": 5, "Kabel verlegen": 4, "Podestboden": 4,
        "Bodenbelag": 5, "Wandbau": 20, "Deckenaufbau": 10, "Einrichtung": 8,
        "Grafik": 8, "Theken und Möbel": 5, "Medientechnik": 5,
        "Pflanzen und Deko": 4, "Reinigung": 3, "Standübergabe": 1
    }
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Prozentuale Verteilung")
    pct = {}
    for t, d in anteile.items():
        pct[t] = st.sidebar.slider(f"{t} [%]", min_value=0, max_value=100, value=d, step=1)

    sum_pct = sum(pct.values()) or 1
    base = {t: total_h * (p / sum_pct) for t, p in pct.items()}

    # Manual adjustment
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ✏️ Manuelle Anpassung Stunden")
    man = {}
    for t, h in base.items():
        man[t] = st.sidebar.number_input(f"{t} (h)", value=round(h, 1), min_value=0.0, step=0.1)

    # Build schedule
    schedule = []
    current_dt = datetime.combine(start_datum, window_start)
    alert_shown = False

    for task, hours in man.items():
        remaining = hours
        while remaining > 0:
            day_start = datetime.combine(current_dt.date(), window_start)
            day_end = datetime.combine(current_dt.date(), window_end)
            if current_dt < day_start:
                current_dt = day_start
            if current_dt >= day_end:
                current_dt = datetime.combine(current_dt.date() + timedelta(days=1), window_start)
                continue

            avail_wall = (day_end - current_dt).seconds / 3600
            possible_man = avail_wall * total_team
            if possible_man <= 0:
                if not alert_shown:
                    st.error("⚠️ Kapazität nicht ausreichend – bitte Teamgröße oder Zeitfenster anpassen.")
                    alert_shown = True
                schedule = []
                break

            alloc = min(remaining, possible_man)
            wall_h = alloc / total_team
            seg_start = current_dt
            seg_end = current_dt + timedelta(hours=wall_h)

            schedule.append({"Task": task, "Start": seg_start, "Finish": seg_end})
            remaining -= alloc
            current_dt = seg_end
        if alert_shown:
            break

    # Team summary
    if schedule:
        start_all = schedule[0]["Start"]
        end_all = schedule[-1]["Finish"]
        total_deploy = (end_all - start_all).total_seconds() / 3600
        ts = pd.DataFrame([
            {"Team": team1_name, "Members": team1, "Time_h": round(total_deploy, 1),
             "Total_h": round(total_deploy * team1, 1)},
            {"Team": team2_name, "Members": team2, "Time_h": round(total_deploy, 1),
             "Total_h": round(total_deploy * team2, 1)},
            {"Team": team3_name, "Members": team3, "Time_h": round(total_deploy, 1),
             "Total_h": round(total_deploy * team3, 1)}
        ])
        st.markdown("## 👷‍♂️ Team-Einsatzübersicht")
        st.table(ts)

        # Display in tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📅 Text", "📊 Gantt", "⬇️ PDF", "⬇️ CSV"])
        with tab1:
            st.markdown("### Zeitplan (Text)")
            for seg in schedule:
                dur = (seg["Finish"] - seg["Start"]).seconds / 3600
                st.write(f"{seg['Start'].strftime('%d.%m.%Y %H:%M')} - "
                         f"{seg['Finish'].strftime('%H:%M')}: {seg['Task']} ({dur:.1f}h)")
        with tab2:
            df_sched = pd.DataFrame(schedule)
            fig = px.timeline(df_sched, x_start="Start", x_end="Finish", y="Task")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
        with tab3:
            st.markdown("## PDF-Export (Querformat)")
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=landscape(A4))
            w, h = landscape(A4)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(40, h-40, f"Projekt: {projektname}")
            c.setFont("Helvetica", 12)
            y = h - 70
            c.drawString(40, y, f"Projektmanager: {pm_name}"); y -= 20
            c.drawString(40, y, f"Techn. Projektleiter: {tpl_name}"); y -= 20
            c.drawString(40, y, f"Bauleitung: {bauleitung_name}"); y -= 20
            c.drawString(40, y, f"Zeitraum: {start_datum.strftime('%d.%m.%Y')} "
                             f"{window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')}"); y -= 20
            # Area summaries
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Fläche je Halle:"); y -= 15
            c.setFont("Helvetica", 10)
            for _, row in df_halle.iterrows():
                c.drawString(60, y, f"{row['Halle']}: {row['qm']} m²"); y -= 12
                if y < 80:
                    c.showPage()
                    y = h - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Fläche je Standtyp:"); y -= 15
            c.setFont("Helvetica", 10)
            for _, row in df_typ.iterrows():
                c.drawString(60, y, f"{row['Standtyp']}: {row['qm']} m²"); y -= 12
                if y < 80:
                    c.showPage()
                    y = h - 40
            # Gantt image
            img_bytes = fig.to_image(format="png", width=1000, height=300)
            img = Image.open(io.BytesIO(img_bytes))
            c.drawImage(ImageReader(img), 40, y-220, width=w-80, height=200)
            # Text plan
            y_text = y - 240
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y_text, "Ablauf:"); y_text -= 15
            c.setFont("Helvetica", 10)
            for seg in schedule:
                line = (f"{seg['Start'].strftime('%d.%m.%Y %H:%M')} - "
                        f"{seg['Finish'].strftime('%H:%M')}: {seg['Task']} "
                        f"({(seg['Finish']-seg['Start']).seconds/3600:.1f}h)")
                if y_text < 40:
                    c.showPage()
                    y_text = h - 40
                c.drawString(40, y_text, line)
                y_text -= 12
            c.showPage()
            c.save()
            buf.seek(0)
            st.download_button("Download PDF", buf, file_name=f"{projektname}.pdf", mime="application/pdf")

        with tab4:
            st.markdown("## CSV-Export")
            # Prepare combined CSV as overview
            combined = []
            for _, row in df_halle.iterrows():
                combined.append({"Section": "Halle", "Key": row["Halle"], "Value": row["qm"]})
            for _, row in df_typ.iterrows():
                combined.append({"Section": "Standtyp", "Key": row["Standtyp"], "Value": row["qm"]})
            for task, hours in man.items():
                combined.append({"Section": "Distribution", "Key": task, "Value": hours})
            for seg in schedule:
                combined.append({"Section": "Schedule", "Key": seg["Task"], 
                                  "Start": seg["Start"].strftime("%d.%m.%Y %H:%M"), 
                                  "Finish": seg["Finish"].strftime("%d.%m.%Y %H:%M")})
            # Team summary
            for _, row in ts.iterrows():
                combined.append({"Section": "Team", "Key": row["Team"], 
                                  "Members": row["Members"], 
                                  "Time_h": row["Time_h"], 
                                  "Total_h": row["Total_h"]})
            df_combined = pd.DataFrame(combined)
            csv_data = df_combined.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV Overview", data=csv_data, file_name=f"{projektname}_overview.csv", mime="text/csv")
    else:
        st.error("⚠️ Kapazität nicht ausreichend – bitte Teamgröße oder Zeitfenster anpassen.")
