import dagster

from posthog.dags import disable_alerts_for_deleted_insights, sessions
from posthog.dags.sessions import sessions_backfill_job

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill, sessions.sessions_v3_backfill_replay],
    jobs=[
        sessions_backfill_job,
        disable_alerts_for_deleted_insights.delete_alerts_for_deleted_insights,
    ],
)
