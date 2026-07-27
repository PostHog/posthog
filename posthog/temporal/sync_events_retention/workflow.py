from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.sync_events_retention.activities import sync_events_retention
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput


@workflow.defn(name="sync-events-retention")
class SyncEventsRetentionWorkflow(PostHogWorkflow):
    inputs_cls = SyncEventsRetentionInput

    @workflow.run
    async def run(self, input: SyncEventsRetentionInput) -> None:
        await workflow.execute_activity(
            sync_events_retention,
            input,
            start_to_close_timeout=timedelta(minutes=120),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=5),
        )
