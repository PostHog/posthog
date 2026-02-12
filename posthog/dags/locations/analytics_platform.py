import dagster

from posthog.dags import sessions, sessions_v1_cleanup
from posthog.dags.sessions import (
    experimental_sessions_backfill_job,
    experimental_sessions_v3_backfill,
    sessions_backfill_job,
)

from . import resources

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill, sessions.sessions_v3_backfill_replay, experimental_sessions_v3_backfill],
    jobs=[sessions_backfill_job, sessions_v1_cleanup.sessions_v1_cleanup_job, experimental_sessions_backfill_job],
    resources=resources,
)
