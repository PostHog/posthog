import asyncio
import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow

from ...facade.contracts import CHECK_SUITE_WORKFLOW_NAME
from ...facade.enums import SuiteRunTrigger
from ..activities.cleanup import cleanup_check_runs_activity
from ..activities.schedule_due_checks import retrieve_due_checks_activity
from ..contracts import CleanupOutcome, DueCheckGroup, RunCheckSuiteInputs

# A scan can claim up to MAX_DUE_CHECKS_PER_SCAN groups; starting them all in one workflow task
# would flood the shared data-modeling queue, so cap concurrent starts the way ExecuteDAGWorkflow
# does. Bounding in-flight starts also bounds the child-start commands emitted per workflow task.
MAX_CONCURRENT_STARTS = 10


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

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_STARTS)

        async def _start(group: DueCheckGroup) -> None:
            async with semaphore:
                await self._start_suite(group)

        results = await asyncio.gather(*[_start(group) for group in groups], return_exceptions=True)

        # The scan already advanced next_run_at for every group, so a group we fail to start here
        # waits a full cadence rather than retrying. Log each failure with its subject and raise so
        # the scan surfaces as failed instead of silently dropping work, since a bare count would
        # hide it. Successfully started children are unaffected: they run under ABANDON.
        failures = [(group, result) for group, result in zip(groups, results) if isinstance(result, BaseException)]
        for group, error in failures:
            workflow.logger.error(
                f"Failed to start check suite for subject {group.subject_uuid} (team {group.team_id}): {error}"
            )
        if failures:
            raise ApplicationError(
                f"{len(failures)} of {len(groups)} check suites failed to start; they retry next cadence"
            )
        return len(groups)

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
