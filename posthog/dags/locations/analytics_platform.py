import dagster

from posthog.dags import session_cleanup, sessions
from posthog.dags.exported_asset_expiry_backfill import exported_asset_expiry_backfill_job
from posthog.dags.sessions import sessions_backfill_job

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill, sessions.sessions_v3_backfill_replay],
    jobs=[sessions_backfill_job, exported_asset_expiry_backfill_job, session_cleanup.expired_session_cleanup_job],
    schedules=[session_cleanup.expired_session_cleanup_schedule],
)
