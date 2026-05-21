from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.backfill_sessions.activities import aggregate_and_upsert_mcp_sessions
from posthog.temporal.mcp_analytics.backfill_sessions.types import BackfillMCPSessionsInput


@workflow.defn(name="backfill-mcp-sessions")
class BackfillMCPSessionsWorkflow(PostHogWorkflow):
    inputs_cls = BackfillMCPSessionsInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: BackfillMCPSessionsInput) -> None:
        await workflow.execute_activity(
            aggregate_and_upsert_mcp_sessions,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
        )
