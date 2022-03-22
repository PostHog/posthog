from django.conf import settings

SESSION_RECORDING_EVENTS_DATA_TABLE = (
    lambda: "sharded_session_recording_events" if settings.CLICKHOUSE_REPLICATION else "session_recording_events"
)

INSERT_SESSION_RECORDING_EVENT_SQL = (
    lambda: f"""
INSERT INTO {SESSION_RECORDING_EVENTS_DATA_TABLE()} (uuid, timestamp, team_id, distinct_id, session_id, window_id, snapshot_data, created_at, _timestamp, _offset)
SELECT %(uuid)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(session_id)s, %(window_id)s, %(snapshot_data)s, %(created_at)s, now(), 0
"""
)
