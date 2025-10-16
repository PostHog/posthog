import json
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.enforce_max_replay_retention.activities import enforce_max_replay_retention
from posthog.temporal.enforce_max_replay_retention.types import EnforceMaxReplayRetentionInput


@workflow.defn(name="enforce-max-replay-retention")
class EnforceMaxReplayRetentionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> EnforceMaxReplayRetentionInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return EnforceMaxReplayRetentionInput(**loaded)

    @workflow.run
    async def run(self, input: EnforceMaxReplayRetentionInput) -> None:
        await workflow.execute_activity(
            enforce_max_replay_retention,
            input,
            start_to_close_timeout=timedelta(minutes=120),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=5),
        )
