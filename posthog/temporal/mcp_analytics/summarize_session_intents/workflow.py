from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.summarize_session_intents.activities import summarize_mcp_session_intents
from posthog.temporal.mcp_analytics.summarize_session_intents.types import SummarizeMCPSessionIntentsInput


@workflow.defn(name="summarize-mcp-session-intents")
class SummarizeMCPSessionIntentsWorkflow(PostHogWorkflow):
    inputs_cls = SummarizeMCPSessionIntentsInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: SummarizeMCPSessionIntentsInput) -> None:
        await workflow.execute_activity(
            summarize_mcp_session_intents,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(seconds=30),
            ),
        )
