from collections import Counter

from django.db.models import QuerySet

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ...facade.enums import CheckRunStatus, CheckSeverity
from ...logic.runner import STAGED_FILES_UNREADABLE, record_unrunnable_check, run_check, staged_subject_is_reachable
from ...logic.staged_audit import StagedSubjectOverride
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import BatchOutcome, RunCheckBatchInputs

LOGGER = get_logger(__name__)


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

    staged = None
    staged_database_cache: dict = {}
    if inputs.staged_queryable_folder and inputs.staged_saved_query_id:
        staged = StagedSubjectOverride(
            saved_query_id=inputs.staged_saved_query_id,
            queryable_folder=inputs.staged_queryable_folder,
        )
        if not staged_subject_is_reachable(team, staged, staged_database_cache):
            return _record_unaudited_batch(checks, suite_run, team)

    counts: Counter[str] = Counter()
    failed_blocking = 0
    newly_failing: list[str] = []
    for check in checks:
        # run_check records a compile or query failure as an errored run rather than raising: one
        # broken check must not fail the activity and take its whole batch down with it.
        result = run_check(check, suite_run, team, staged=staged, staged_database_cache=staged_database_cache)
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
