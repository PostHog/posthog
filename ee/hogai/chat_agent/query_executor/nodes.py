from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import ArtifactMessage, AssistantMessage, AssistantToolCallMessage, FailureMessage

from ee.hogai.artifacts.utils import is_visualization_artifact_message
from ee.hogai.chat_agent.query_executor.query_executor import execute_and_format_query
from ee.hogai.core.node import AssistantNode
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery


class QueryExecutorNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        last_message = state.messages[-1]
        if isinstance(last_message, FailureMessage):
            return None  # Exit early - something failed earlier

        if not is_visualization_artifact_message(last_message):
            return None

        query = await self._extract_query(last_message)

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

    async def _extract_query(self, message: ArtifactMessage) -> AnyAssistantGeneratedQuery:
        if not message.artifact_id:
            raise ValueError("ArtifactMessage must have a artifact_id")
        content = await self.context_manager.artifacts.aget_visualization_content_by_short_id(message.artifact_id)
        return cast(AnyAssistantGeneratedQuery, content.query)
