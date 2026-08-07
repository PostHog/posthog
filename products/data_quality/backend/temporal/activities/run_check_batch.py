from collections import Counter

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ...facade.enums import CheckRunStatus
from ...logic.runner import run_check
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import BatchOutcome, RunCheckBatchInputs

LOGGER = get_logger(__name__)


@activity.defn
async def run_check_batch_activity(inputs: RunCheckBatchInputs) -> BatchOutcome:
    async with Heartbeater():
        return await sync_to_async(_run_batch)(inputs)


def _run_batch(inputs: RunCheckBatchInputs) -> BatchOutcome:
    team = Team.objects.get(id=inputs.team_id)
    suite_run = DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id)
    checks = DataQualityCheck.objects.for_team(inputs.team_id).filter(id__in=inputs.check_ids)

    # A retry after the previous attempt committed rows but died before Temporal recorded its result
    # would otherwise leave two runs per check in one suite, double-counting the report. One suite
    # run means one row per check, so clear this batch's rows before re-running it.
    DataQualityCheckRun.objects.for_team(inputs.team_id).filter(
        suite_run=suite_run, quality_check_id__in=inputs.check_ids
    ).delete()

    counts: Counter[str] = Counter()
    newly_failing: list[str] = []
    for check in checks:
        # run_check records a compile or query failure as an errored run rather than raising: one
        # broken check must not fail the activity and take its whole batch down with it.
        result = run_check(check, suite_run, team)
        counts[result.status] += 1
        if result.became_failing:
            newly_failing.append(str(check.id))

    LOGGER.info("Ran check batch", suite_run_id=inputs.suite_run_id, checks=len(inputs.check_ids))
    return BatchOutcome(
        passed=counts[CheckRunStatus.PASSED],
        failed=counts[CheckRunStatus.FAILED],
        errored=counts[CheckRunStatus.ERRORED],
        skipped=counts[CheckRunStatus.SKIPPED],
        newly_failing_check_ids=newly_failing,
    )
