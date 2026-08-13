from collections import Counter

from django.db.models import QuerySet

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ...facade.enums import CheckRunStatus, CheckSeverity
from ...logic.runner import record_unrunnable_check, run_check
from ...logic.staged_audit import build_staged_database
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import BatchOutcome, RunCheckBatchInputs

LOGGER = get_logger(__name__)

STAGED_FILES_UNREADABLE = "The staged files could not be read, so this data was not audited."


@activity.defn
async def run_check_batch_activity(inputs: RunCheckBatchInputs) -> BatchOutcome:
    async with Heartbeater():
        return await sync_to_async(_run_batch)(inputs)


def _record_unaudited_batch(
    checks: "QuerySet[DataQualityCheck]",
    suite_run: DataQualitySuiteRun,
    team: Team,
) -> BatchOutcome:
    """Error every check in the batch, leaving ``failed_blocking`` at zero so a gate publishes."""
    errored = 0
    for check in checks:
        record_unrunnable_check(check, suite_run, team, STAGED_FILES_UNREADABLE)
        errored += 1
    LOGGER.warning("Could not audit staged files", suite_run_id=str(suite_run.id), checks=errored)
    return BatchOutcome(errored=errored)


def _run_batch(inputs: RunCheckBatchInputs) -> BatchOutcome:
    team = Team.objects.get(id=inputs.team_id)
    suite_run = DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id)
    checks = DataQualityCheck.objects.for_team(inputs.team_id).filter(
        id__in=inputs.check_ids, enabled=True, deleted=False
    )

    DataQualityCheckRun.objects.for_team(inputs.team_id).filter(
        suite_run=suite_run, quality_check_id__in=inputs.check_ids
    ).delete()

    staged_database = None
    if inputs.staged_queryable_folder and inputs.staged_saved_query_id:
        staged_database = build_staged_database(team, inputs.staged_saved_query_id, inputs.staged_queryable_folder)
        if staged_database is None:
            return _record_unaudited_batch(checks, suite_run, team)

    counts: Counter[str] = Counter()
    failed_blocking = 0
    newly_failing: list[str] = []
    for check in checks:
        result = run_check(check, suite_run, team, database=staged_database)
        counts[result.status] += 1
        if result.status is CheckRunStatus.FAILED and check.severity == CheckSeverity.ERROR:
            failed_blocking += 1
        if result.became_failing:
            newly_failing.append(str(check.id))

    LOGGER.info("Ran check batch", suite_run_id=inputs.suite_run_id, checks=len(inputs.check_ids))
    return BatchOutcome(
        passed=counts[CheckRunStatus.PASSED],
        failed=counts[CheckRunStatus.FAILED],
        errored=counts[CheckRunStatus.ERRORED],
        skipped=counts[CheckRunStatus.SKIPPED],
        failed_blocking=failed_blocking,
        newly_failing_check_ids=newly_failing,
    )
