import dagster

from posthog.dags import sessions
from posthog.dags.backfill_test_users_cohort import backfill_test_users_cohort
from posthog.dags.sessions import sessions_backfill_job

defs = dagster.Definitions(
    assets=[sessions.sessions_v3_backfill, sessions.sessions_v3_backfill_replay],
    jobs=[sessions_backfill_job, backfill_test_users_cohort],
)
