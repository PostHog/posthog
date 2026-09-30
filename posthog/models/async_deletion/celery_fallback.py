"""Gating for the Celery cleanup sweeps, which exist only for deployments without Dagster.

PostHog Cloud runs `clickhouse_deletion_sweep_job` instead. Two sweeps mutating `person` and
`person_distinct_id2` at once is the thing this prevents.
"""

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_hobby

logger = structlog.get_logger(__name__)

# The Dagster sweep runs weekly, so a month of silence means it does not run here.
DAGSTER_ACTIVITY_WINDOW_DAYS = 30

# The Celery sweep is unattended and uncapped by its caller, so it carries the Dagster default.
CELERY_SWEEP_MAX_COHORTS = 2_000


def celery_sweeps_enabled() -> bool:
    """Whether this deployment should run the Celery cleanup sweeps."""
    return is_hobby() and not dagster_sweep_is_active()


def dagster_sweep_is_active() -> bool:
    """Whether the Dagster sweep has run here in the last `DAGSTER_ACTIVITY_WINDOW_DAYS`.

    `derive_run_mode` resolves an unrecognized `CLOUD_DEPLOYMENT` to HOBBY, so `is_hobby()` reads
    true on a cloud deployment whose region is misspelled. This is the independent check on that.

    The counter is append-only, unlike `person_pg_cleanup_queue`, whose rows the Postgres drain
    deletes as it resolves them. An unreadable table means no Dagster sweep here.
    """
    try:
        [[runs]] = sync_execute(
            """
            SELECT count()
            FROM custom_metrics_counter_events
            WHERE name = 'clickhouse_cleanup_delete_pass_total'
              AND timestamp > now() - INTERVAL %(days)s DAY
            """,
            {"days": DAGSTER_ACTIVITY_WINDOW_DAYS},
        )
        return runs > 0
    except Exception:
        logger.info("clickhouse_cleanup counters unreadable, treating the Dagster sweep as absent")
        return False
