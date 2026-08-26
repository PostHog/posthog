from datetime import UTC, datetime

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from ...facade.enums import SuiteRunStatus
from ...models import DataQualitySuiteRun
from ..contracts import CheckSuiteResult, FinalizeCheckSuiteInputs, MarkSuiteFailedInputs

LOGGER = get_logger(__name__)


@activity.defn
async def finalize_check_suite_activity(inputs: FinalizeCheckSuiteInputs) -> CheckSuiteResult:
    return await sync_to_async(_finalize)(inputs)


def _finalize(inputs: FinalizeCheckSuiteInputs) -> CheckSuiteResult:
    suite_run = DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id)

    suite_run.checks_passed = sum(outcome.passed for outcome in inputs.outcomes)
    suite_run.checks_failed = sum(outcome.failed for outcome in inputs.outcomes)
    suite_run.checks_errored = sum(outcome.errored for outcome in inputs.outcomes)
    suite_run.checks_skipped = sum(outcome.skipped for outcome in inputs.outcomes)
    suite_run.status = SuiteRunStatus.COMPLETED
    suite_run.finished_at = datetime.now(UTC)
    suite_run.save(
        update_fields=[
            "checks_passed",
            "checks_failed",
            "checks_errored",
            "checks_skipped",
            "status",
            "finished_at",
            "updated_at",
        ]
    )

    LOGGER.info(
        "Finalized check suite",
        suite_run_id=inputs.suite_run_id,
        passed=suite_run.checks_passed,
        failed=suite_run.checks_failed,
        errored=suite_run.checks_errored,
    )
    return CheckSuiteResult(
        suite_run_id=str(suite_run.id),
        status=SuiteRunStatus.COMPLETED,
        checks_passed=suite_run.checks_passed,
        checks_failed=suite_run.checks_failed,
        checks_errored=suite_run.checks_errored,
        checks_skipped=suite_run.checks_skipped,
        checks_failed_blocking=sum(outcome.failed_blocking for outcome in inputs.outcomes),
    )


@activity.defn
async def mark_check_suite_empty_activity(inputs: FinalizeCheckSuiteInputs) -> CheckSuiteResult:
    return await sync_to_async(_mark_empty)(inputs)


def _mark_empty(inputs: FinalizeCheckSuiteInputs) -> CheckSuiteResult:
    """An empty suite is a normal outcome, not a failure -- most materializations have no checks."""
    suite_run = DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id)
    suite_run.status = SuiteRunStatus.EMPTY
    suite_run.finished_at = datetime.now(UTC)
    suite_run.save(update_fields=["status", "finished_at", "updated_at"])
    return CheckSuiteResult(suite_run_id=str(suite_run.id), status=SuiteRunStatus.EMPTY)


@activity.defn
async def mark_check_suite_failed_activity(inputs: MarkSuiteFailedInputs) -> None:
    await sync_to_async(_mark_failed)(inputs)


def _mark_failed(inputs: MarkSuiteFailedInputs) -> None:
    """Move a suite off RUNNING when the workflow gives up, so a poller sees a terminal state.

    A conditional update rather than a load-and-save: it must not clobber a suite another attempt
    already finalized, and it stays a no-op when there is nothing to fail.
    """
    updated = (
        DataQualitySuiteRun.objects.for_team(inputs.team_id)
        .filter(id=inputs.suite_run_id, status=SuiteRunStatus.RUNNING)
        .update(
            status=SuiteRunStatus.FAILED,
            error=inputs.error,
            finished_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    LOGGER.info("Marked check suite failed", suite_run_id=inputs.suite_run_id, updated=updated)
