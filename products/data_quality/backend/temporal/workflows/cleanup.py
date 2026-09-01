import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from ..activities.cleanup import cleanup_check_runs_activity
from ..contracts import CleanupOutcome


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
