from datetime import UTC, datetime, timedelta

from django.db.models import Exists, OuterRef, Q

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from ...facade.enums import SuiteRunStatus
from ...models import DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import CleanupOutcome

LOGGER = get_logger(__name__)

COMPILED_QUERY_RETENTION_DAYS = 30
CHECK_RUN_RETENTION_DAYS = 365
SUITE_RUN_RETENTION_DAYS = 90
STALE_SUITE_HOURS = 24
STALE_SUITE_ERROR = "The workflow stopped without recording a result."


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

    has_newer_run = runs.filter(quality_check_id=OuterRef("quality_check_id"), created_at__gt=OuterRef("created_at"))
    # .delete() returns the total across every cascaded model. Count only the runs -- the subject
    # index rows that cascade with each run would otherwise inflate the reported figure.
    _, deleted_by_model = (
        runs.filter(created_at__lt=now - timedelta(days=CHECK_RUN_RETENTION_DAYS))
        .filter(Q(quality_check_id__isnull=True) | Exists(has_newer_run))
        .delete()
    )
    runs_deleted = deleted_by_model.get(DataQualityCheckRun._meta.label, 0)

    backs_a_run = DataQualityCheckRun.objects.unscoped().filter(suite_run_id=OuterRef("id"))
    suites_deleted, _ = (
        DataQualitySuiteRun.objects.unscoped()
        .filter(created_at__lt=now - timedelta(days=SUITE_RUN_RETENTION_DAYS))
        .filter(~Exists(backs_a_run))
        .delete()
    )

    stale_failed = (
        DataQualitySuiteRun.objects.unscoped()
        .filter(status=SuiteRunStatus.RUNNING, created_at__lt=now - timedelta(hours=STALE_SUITE_HOURS))
        .update(status=SuiteRunStatus.FAILED, error=STALE_SUITE_ERROR, finished_at=now, updated_at=now)
    )

    LOGGER.info(
        "Cleaned up data quality history",
        queries_cleared=queries_cleared,
        runs_deleted=runs_deleted,
        suites_deleted=suites_deleted,
        stale_suites_failed=stale_failed,
    )
    return CleanupOutcome(
        compiled_queries_cleared=queries_cleared,
        check_runs_deleted=runs_deleted,
        suite_runs_deleted=suites_deleted,
        stale_suites_failed=stale_failed,
    )
