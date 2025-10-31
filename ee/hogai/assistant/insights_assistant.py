from collections.abc import AsyncGenerator
from typing import Any, Optional
from uuid import UUID

from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext, VisualizationMessage

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph.graph import InsightsAssistantGraph
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantMode,
    AssistantState,
    MessageAction,
    PartialAssistantState,
)
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

    def get_initial_state(self) -> AssistantState:
        return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        return PartialAssistantState(
            messages=[self._latest_message], graph_status="resumed", query_generation_retry_count=0
        )

    async def astream(self, stream_first_message: bool = False) -> AsyncGenerator[AssistantDispatcherEvent, None]:
        last_ai_message: AssistantMessage | None = None
        last_viz_message: VisualizationMessage | None = None

        async for dispatcher_event in super().astream(stream_first_message=stream_first_message):
            # Track messages for reporting
            if isinstance(dispatcher_event.action, MessageAction):
                message = dispatcher_event.action.message
                if isinstance(message, VisualizationMessage):
                    last_viz_message = message
                if isinstance(message, AssistantMessage):
                    last_ai_message = message
            yield dispatcher_event

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
