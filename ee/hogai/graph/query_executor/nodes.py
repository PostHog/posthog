from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, FailureMessage, VisualizationMessage

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.query_executor.query_executor import execute_and_format_query
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName


class QueryExecutorNode(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.QUERY_EXECUTOR

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        viz_message = state.messages[-1]
        if isinstance(viz_message, FailureMessage):
            return None  # Exit early - something failed earlier
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError(f"Expected a visualization message, found {type(viz_message)}")
        if viz_message.answer is None:
            raise ValueError("Did not find query in the visualization message")

        tool_call_id = state.root_tool_call_id
        if not tool_call_id:
            return None

        formatted_query_result = await execute_and_format_query(self._team, viz_message.answer)

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_query_result, id=str(uuid4()), tool_call_id=tool_call_id)
            ],
            root_tool_call_id=None,
            root_tool_insight_plan=None,
            root_tool_insight_type=None,
            rag_context=None,
        )
