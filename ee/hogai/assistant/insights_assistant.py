from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext, VisualizationMessage

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph.insights_graph.graph import InsightsGraph
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types import AssistantMode, AssistantOutput, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.models import Conversation

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


VERBOSE_NODES: set["MaxNodeName"] = {
    AssistantNodeName.QUERY_EXECUTOR,
    AssistantNodeName.FUNNEL_GENERATOR,
    AssistantNodeName.RETENTION_GENERATOR,
    AssistantNodeName.SQL_GENERATOR,
    AssistantNodeName.TRENDS_GENERATOR,
    AssistantNodeName.ROOT,
    AssistantNodeName.AGENT_EXECUTOR,
    AssistantNodeName.AGENT_EXECUTOR_TOOLS,
}


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
            graph=InsightsGraph(team, user).compile_full_graph(),
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            mode=AssistantMode.INSIGHTS_TOOL,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
            stream_processor=AssistantStreamProcessor(
                verbose_nodes=VERBOSE_NODES, streaming_nodes=set(), state_type=AssistantState
            ),
        )

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
