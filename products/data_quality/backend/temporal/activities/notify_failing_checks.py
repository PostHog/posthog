import time
from datetime import UTC, datetime

from temporalio import activity

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ...facade.enums import CheckRunStatus, CheckSeverity
from ...logic.notifications import notify_check_started_failing
from ...logic.runner import FAILING_STATUSES
from ...models import DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import NotifyFailingChecksInputs

LOGGER = get_logger(__name__)


@activity.defn
async def notify_failing_checks_activity(inputs: NotifyFailingChecksInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async_pool(_notify_failing_checks)(inputs)


def _notify_failing_checks(inputs: NotifyFailingChecksInputs) -> None:
    """Tell the team about every check this suite moved into failing.

    Derived from the streak each check persisted, never from what a batch reported, so a batch that
    claimed the streak and then timed out still notifies on its retry.
    """
    suite_run = DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id)
    runs = _runs_that_started_failing(inputs.team_id, suite_run)
    access_cache: dict[int, UserAccessControl] = {}
    notified = 0

    for run in runs:
        check = run.quality_check
        if check is None or check.failing_since is None:
            continue
        started = time.monotonic()
        recipients = notify_check_started_failing(
            check,
            run.failed_row_count,
            executed_references=run.referenced_subjects,
            idempotency_key=failing_streak_key(str(check.id), check.failing_since),
            access_cache=access_cache,
        )
        notified += 1
        LOGGER.info(
            "Notified a newly failing check",
            suite_run_id=inputs.suite_run_id,
            check_id=str(check.id),
            recipients=recipients,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    LOGGER.info(
        "Notified the checks a suite moved into failing",
        suite_run_id=inputs.suite_run_id,
        checks=notified,
        members=len(access_cache),
    )


def failing_streak_key(check_id: str, failing_since: datetime) -> str:
    """The idempotency key for one streak, so overlapping suites collapse to a single notice."""
    return f"check-failing-{check_id}-{failing_since.isoformat()}"


def _runs_that_started_failing(team_id: int, suite_run: DataQualitySuiteRun) -> list[DataQualityCheckRun]:
    """The suite's failed runs whose check is still failing on a streak this suite opened.

    Severity comes from the run row, not the definition, so an edit between the batch and this
    activity cannot change what the suite already reported, or make one retry differ from the next.
    """
    opened_from, opened_until = _streak_window(suite_run)
    return list(
        DataQualityCheckRun.objects.for_team(team_id)
        .filter(
            suite_run_id=suite_run.id,
            status=CheckRunStatus.FAILED,
            check_severity=CheckSeverity.ERROR,
            quality_check__last_status__in=FAILING_STATUSES,
            quality_check__failing_since__gte=opened_from,
            quality_check__failing_since__lte=opened_until,
        )
        .select_related("quality_check")
    )


def _streak_window(suite_run: DataQualitySuiteRun) -> tuple[datetime, datetime]:
    """When a streak has to have started for this suite to be the one that opened it.

    Bounded at both ends. A check that recovers and fails again after this suite finished is on a
    streak another suite opened, and its own notice carries that run's row count and references.
    """
    return suite_run.started_at or suite_run.created_at, suite_run.finished_at or datetime.now(UTC)
