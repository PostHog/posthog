import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .activities import StopRunsOverQuotaInputs, StopRunsOverQuotaResult, stop_cloud_agent_runs_over_quota_activity

WORKFLOW_NAME = "cloud-agents-stop-runs-over-quota"


@workflow.defn(name=WORKFLOW_NAME)
class StopCloudAgentRunsOverQuotaWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self) -> StopRunsOverQuotaResult:
        return await workflow.execute_activity(
            stop_cloud_agent_runs_over_quota_activity,
            StopRunsOverQuotaInputs(),
            start_to_close_timeout=dt.timedelta(minutes=4),
            heartbeat_timeout=dt.timedelta(minutes=1),
            # The next run of the schedule continues the work, so a failed run needs few attempts.
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=dt.timedelta(seconds=10)),
        )
