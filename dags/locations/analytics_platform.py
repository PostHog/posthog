import dagster

from dags import sessions

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill],
)
