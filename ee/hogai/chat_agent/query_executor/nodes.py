from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCallMessage, FailureMessage

from ee.hogai.artifacts.utils import unwrap_visualization_artifact_content
from ee.hogai.chat_agent.query_executor.query_executor import execute_and_format_query
from ee.hogai.core.node import AssistantNode
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, ArtifactRefMessage


class QueryExecutorNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        query = await self._extract_query(state)
        if not query:
            return None

        tool_call_id = state.root_tool_call_id
        if not tool_call_id:
            return None

        try:
            formatted_query_result = await execute_and_format_query(self._team, query)
        except MaxToolRetryableError as err:
            # Handle known query execution errors (exposed to users)
            return PartialAssistantState(
                messages=[
                    AssistantMessage(content=f"There was an error running this query: {str(err)}", id=str(uuid4()))
                ]
            )
        except Exception:
            # Handle unknown errors
            return PartialAssistantState(
                messages=[AssistantMessage(content="There was an unknown error running this query.", id=str(uuid4()))]
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

    async def _extract_query(self, state: AssistantState) -> AnyAssistantGeneratedQuery | None:
        last_message = state.messages[-1]
        if isinstance(last_message, FailureMessage):
            return None  # Exit early - something failed earlier

        if not isinstance(last_message, ArtifactRefMessage):
            raise ValueError("Expected an ArtifactRefMessage, found <class 'posthog.schema.HumanMessage'>")

        enriched_messages = await self.context_manager.artifacts.aenrich_messages(state.messages, artifacts_only=True)
        if not enriched_messages:
            raise ValueError("No messages found")
        enriched_message = next(message for message in enriched_messages if message.id == last_message.id)
        if not enriched_message:
            raise ValueError("No enriched message found")
        content = unwrap_visualization_artifact_content(enriched_message)
        if not content:
            raise ValueError("Content must be a VisualizationArtifactContent")
        return cast(AnyAssistantGeneratedQuery, content.query)
