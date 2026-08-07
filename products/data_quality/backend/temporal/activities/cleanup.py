from datetime import UTC, datetime, timedelta

from django.db.models import Exists, OuterRef, Q

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from ...facade.enums import SuiteRunStatus
from ...models import DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import CleanupOutcome

LOGGER = get_logger(__name__)

# The compiled query is the biggest column on a run row and is only useful while someone might
# still re-run it to see the offending rows.
COMPILED_QUERY_RETENTION_DAYS = 30
# A year of numeric history is the training window future anomaly-detection check types need.
CHECK_RUN_RETENTION_DAYS = 365
EMPTY_SUITE_RUN_RETENTION_DAYS = 90


@activity.defn
async def cleanup_check_runs_activity() -> CleanupOutcome:
    return await sync_to_async(_cleanup)()


def _cleanup() -> CleanupOutcome:
    """Retention sweep across every team, which is why it uses the unscoped manager."""
    now = datetime.now(UTC)
    runs = DataQualityCheckRun.objects.unscoped()

    queries_cleared = (
        runs.filter(created_at__lt=now - timedelta(days=COMPILED_QUERY_RETENTION_DAYS))
        .exclude(compiled_query="")
        .update(compiled_query="")
    )

    # Delete an aged-out run only when a newer one exists for the same check, so a subject's health
    # survives retention even if nothing has run it for a year. Runs whose definition is gone have
    # no health to preserve and age out unconditionally.
    has_newer_run = runs.filter(quality_check_id=OuterRef("quality_check_id"), created_at__gt=OuterRef("created_at"))
    runs_deleted, _ = (
        runs.filter(created_at__lt=now - timedelta(days=CHECK_RUN_RETENTION_DAYS))
        .filter(Q(quality_check_id__isnull=True) | Exists(has_newer_run))
        .delete()
    )

    suites_deleted, _ = (
        DataQualitySuiteRun.objects.unscoped()
        .filter(
            status=SuiteRunStatus.EMPTY,
            created_at__lt=now - timedelta(days=EMPTY_SUITE_RUN_RETENTION_DAYS),
        )
        .delete()
    )

    LOGGER.info(
        "Cleaned up data quality history",
        queries_cleared=queries_cleared,
        runs_deleted=runs_deleted,
        suites_deleted=suites_deleted,
    )
    return CleanupOutcome(
        compiled_queries_cleared=queries_cleared,
        check_runs_deleted=runs_deleted,
        empty_suite_runs_deleted=suites_deleted,
    )
