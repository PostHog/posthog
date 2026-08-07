import asyncio
import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

from ...facade.contracts import CHECK_SUITE_WORKFLOW_NAME
from ...facade.enums import SuiteRunTrigger
from ..activities.cleanup import cleanup_check_runs_activity
from ..activities.schedule_due_checks import retrieve_due_checks_activity
from ..contracts import CleanupOutcome, DueCheckGroup, RunCheckSuiteInputs


@workflow.defn(name="schedule-due-data-quality-checks")
class ScheduleDueChecksWorkflow(PostHogWorkflow):
    """Central scanner for per-check schedules.

    One cron scanning ``next_run_at`` rather than a Temporal Schedule per check: thousands of cheap
    checks would bloat the schedule fleet, and namespace-listing rate limits are already a
    documented pain in data_modeling.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> int:
        groups: list[DueCheckGroup] = await workflow.execute_activity(
            retrieve_due_checks_activity,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not groups:
            return 0

        results = await asyncio.gather(*[self._start_suite(group) for group in groups], return_exceptions=True)
        return sum(1 for result in results if not isinstance(result, BaseException))

    async def _start_suite(self, group: DueCheckGroup) -> None:
        try:
            await workflow.start_child_workflow(
                CHECK_SUITE_WORKFLOW_NAME,
                RunCheckSuiteInputs(
                    team_id=group.team_id,
                    trigger=SuiteRunTrigger.SCHEDULE,
                    subject_type=group.subject_type,
                    subject_uuids=[group.subject_uuid],
                    check_ids=group.check_ids,
                ),
                # Deterministic per subject and slot: two overlapping scans cannot double-run a
                # subject, because Temporal rejects a duplicate id while the first is still open.
                id=f"data-quality-schedule-{group.team_id}-{group.subject_uuid}",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(hours=1),
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info(f"Checks for subject {group.subject_uuid} are still running, skipping this tick")


@workflow.defn(name="cleanup-data-quality-check-runs")
class CleanupCheckRunsWorkflow(PostHogWorkflow):
    """Daily retention sweep over check-run history."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> CleanupOutcome:
        return await workflow.execute_activity(
            cleanup_check_runs_activity,
            start_to_close_timeout=dt.timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
