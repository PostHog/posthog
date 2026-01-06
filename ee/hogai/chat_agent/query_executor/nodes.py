from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import ArtifactMessage, AssistantMessage, AssistantToolCallMessage, FailureMessage

from ee.hogai.artifacts.utils import unwrap_visualization_artifact_content
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.core.node import AssistantNode
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class QueryExecutorNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        artifact = await self._extract_artifact(state)
        if not artifact:
            return None

        tool_call_id = state.root_tool_call_id
        if not tool_call_id:
            return None

        content = unwrap_visualization_artifact_content(artifact)
        if not content:
            raise ValueError("Content must be a VisualizationArtifactContent")

        try:
            context = InsightContext(
                team=self._team,
                query=content.query,
                name=content.name,
                description=content.description,
                insight_id=artifact.artifact_id,
            )
            formatted_query_result = await context.execute_and_format()
        except MaxToolRetryableError as err:
            # Handle known query execution errors (exposed to users)
            return PartialAssistantState(
                messages=[
                    AssistantMessage(content=f"There was an error running this query: {str(err)}", id=str(uuid4()))
                ]
            )

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_query_result, id=str(uuid4()), tool_call_id=tool_call_id)
            ],
            root_tool_call_id=None,
            root_tool_insight_plan=None,
            root_tool_insight_type=None,
            rag_context=None,
        )

    async def _extract_artifact(self, state: AssistantState) -> ArtifactMessage | None:
        last_message = state.messages[-1]
        if isinstance(last_message, FailureMessage):
            return None  # Exit early - something failed earlier

        if not isinstance(last_message, ArtifactRefMessage):
            raise ValueError(f"Expected an ArtifactRefMessage, found {type(last_message)}")

        enriched_messages = await self.context_manager.artifacts.aenrich_messages(state.messages, artifacts_only=True)
        if not enriched_messages:
            raise ValueError("No messages found")
        enriched_message = next(message for message in enriched_messages if message.id == last_message.id)
        if not enriched_message:
            raise ValueError("No enriched message found")
        if not isinstance(enriched_message, ArtifactMessage):
            raise ValueError("Expected an ArtifactMessage")
        return enriched_message
