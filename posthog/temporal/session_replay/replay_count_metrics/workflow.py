from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.replay_count_metrics.activities import collect_replay_count_metrics
from posthog.temporal.session_replay.replay_count_metrics.types import ReplayCountMetricsInput


@workflow.defn(name="replay-count-metrics")
class ReplayCountMetricsWorkflow(PostHogWorkflow):
    inputs_cls = ReplayCountMetricsInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: ReplayCountMetricsInput) -> None:
        await workflow.execute_activity(
            collect_replay_count_metrics,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
        )
