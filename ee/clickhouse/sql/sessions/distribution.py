from ee.clickhouse.sql.sessions.no_events import SESSIONS_NO_EVENTS_SQL

DIST_SQL = """
    SELECT 
        countIf(session_duration_seconds = 0)  as first,
        countIf(session_duration_seconds > 0 and session_duration_seconds <= 3)  as second,
        countIf(session_duration_seconds > 3 and session_duration_seconds <= 10)  as third,
        countIf(session_duration_seconds > 10 and session_duration_seconds <= 30)  as fourth,
        countIf(session_duration_seconds > 30 and session_duration_seconds <= 60)  as fifth,
        countIf(session_duration_seconds > 60 and session_duration_seconds <= 180)  as sixth,
        countIf(session_duration_seconds > 180 and session_duration_seconds <= 600)  as sevent,
        countIf(session_duration_seconds > 600 and session_duration_seconds <= 1800)  as eighth,
        countIf(session_duration_seconds > 1800 and session_duration_seconds <= 3600)  as ninth,
        countIf(session_duration_seconds > 3600)  as tenth
    FROM 
        ({sessions})
""".format(
    sessions=SESSIONS_NO_EVENTS_SQL
)
