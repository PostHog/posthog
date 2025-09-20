from collections.abc import AsyncGenerator
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    HumanMessage,
    MaxBillingContext,
    VisualizationMessage,
)

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph import FunnelGeneratorNode, RetentionGeneratorNode, SQLGeneratorNode, TrendsGeneratorNode
from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.graph import InsightsAssistantGraph
from ee.hogai.graph.query_executor.nodes import QueryExecutorNode
from ee.hogai.graph.taxonomy.types import TaxonomyNodeName
from ee.hogai.utils.state import GraphValueUpdateTuple, validate_value_update
from ee.hogai.utils.types import (
    AssistantMode,
    AssistantNodeName,
    AssistantOutput,
    AssistantState,
    PartialAssistantState,
)
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models import Conversation


class InsightsAssistant(BaseAssistant):
    _state: Optional[AssistantState]
    _initial_state: Optional[AssistantState | PartialAssistantState]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantState | PartialAssistantState] = None,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph=InsightsAssistantGraph(team, user).compile_full_graph(),
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            mode=AssistantMode.INSIGHTS_TOOL,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
        )

    @property
    def VISUALIZATION_NODES(self) -> dict[MaxNodeName, type[BaseAssistantNode]]:
        return {
            AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
            AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
            AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
            AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
            AssistantNodeName.QUERY_EXECUTOR: QueryExecutorNode,
        }

    @property
    def STREAMING_NODES(self) -> set[MaxNodeName]:
        return {
            TaxonomyNodeName.LOOP_NODE,
        }

    @property
    def VERBOSE_NODES(self) -> set[MaxNodeName]:
        return self.STREAMING_NODES

    @property
    def THINKING_NODES(self) -> set[MaxNodeName]:
        return self.VISUALIZATION_NODES.keys() | {
            AssistantNodeName.QUERY_PLANNER,
            TaxonomyNodeName.LOOP_NODE,
        }

    def get_initial_state(self) -> AssistantState:
        return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        return PartialAssistantState(
            messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
        )

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = False,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        last_ai_message: AssistantMessage | None = None
        last_viz_message: VisualizationMessage | None = None

        # stream_first_message is always False for this mode
        async for stream_event in super().astream(
            stream_message_chunks, stream_subgraphs, False, stream_only_assistant_messages
        ):
            _, message = stream_event
            if isinstance(message, VisualizationMessage):
                last_viz_message = message
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event

        if not self._initial_state:
            return
        visualization_response = last_viz_message.model_dump_json(exclude_none=True) if last_viz_message else None
        await self._report_conversation_state(
            "standalone ai tool call",
            {
                "prompt": self._initial_state.root_tool_insight_plan,
                "output": last_ai_message,
                "response": visualization_response,
                "tool_name": "create_and_query_insight",
                "is_new_conversation": False,
            },
        )

    def _process_value_update(self, update: GraphValueUpdateTuple) -> list[BaseModel] | None:
        _, maybe_state_update = update
        state_update = validate_value_update(maybe_state_update)
        if intersected_nodes := state_update.keys() & self.VISUALIZATION_NODES.keys():
            node_name: MaxNodeName = intersected_nodes.pop()
            node_val = state_update[node_name]
            if isinstance(node_val, PartialAssistantState) and node_val.intermediate_steps:
                return [AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.GENERATION_ERROR)]
        return super()._process_value_update(update)
