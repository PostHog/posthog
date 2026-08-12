from collections import Counter

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ...facade.enums import CheckRunStatus, CheckSeverity
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
    checks = DataQualityCheck.objects.for_team(inputs.team_id).filter(
        id__in=inputs.check_ids, enabled=True, deleted=False
    )

    DataQualityCheckRun.objects.for_team(inputs.team_id).filter(
        suite_run=suite_run, quality_check_id__in=inputs.check_ids
    ).delete()

    counts: Counter[str] = Counter()
    failed_blocking = 0
    newly_failing: list[str] = []
    for check in checks:
        result = run_check(check, suite_run, team)
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
