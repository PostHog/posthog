import dagster

from dags import sessions
from dags.sessions import sessions_backfill_job

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill, sessions.sessions_v3_backfill_replay], jobs=[sessions_backfill_job]
)
