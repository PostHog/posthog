from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.sync_events_retention.activities import sync_events_retention
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput, SyncEventsRetentionResult


@workflow.defn(name="sync-events-retention")
class SyncEventsRetentionWorkflow(PostHogWorkflow):
    inputs_cls = SyncEventsRetentionInput

    @workflow.run
    async def run(self, input: SyncEventsRetentionInput) -> None:
        result: SyncEventsRetentionResult = await workflow.execute_activity(
            sync_events_retention,
            input,
            start_to_close_timeout=timedelta(minutes=120),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=5),
        )
        if input.slo is not None:
            input.slo.completion_properties.update(
                {"total_processed": result.total_processed, "total_updated": result.total_updated}
            )
