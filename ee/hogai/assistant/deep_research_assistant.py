from collections.abc import AsyncGenerator
from typing import Any, Optional
from uuid import UUID

from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.graph.deep_research.graph import DeepResearchAssistantGraph
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantMode, MessageAction
from ee.models import Conversation


class DeepResearchAssistant(BaseAssistant):
    _state: Optional[DeepResearchState]
    _initial_state: Optional[DeepResearchState | PartialDeepResearchState]

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
        initial_state: Optional[DeepResearchState | PartialDeepResearchState] = None,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph=DeepResearchAssistantGraph(team, user).compile_full_graph(),
            state_type=DeepResearchState,
            partial_state_type=PartialDeepResearchState,
            mode=AssistantMode.DEEP_RESEARCH,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
        )

    def get_initial_state(self) -> DeepResearchState:
        if self._latest_message:
            return DeepResearchState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                graph_status=None,
                conversation_notebooks=[],
                current_run_notebooks=None,
            )
        else:
            return DeepResearchState(messages=[])

    def get_resumed_state(self) -> PartialDeepResearchState:
        if not self._latest_message:
            return PartialDeepResearchState(messages=[])
        return PartialDeepResearchState(messages=[self._latest_message], graph_status="resumed")

    async def astream(self, stream_first_message: bool = True) -> AsyncGenerator[AssistantDispatcherEvent, None]:
        last_ai_message: AssistantMessage | None = None
        async for dispatcher_event in super().astream(stream_first_message=stream_first_message):
            if isinstance(dispatcher_event.action, MessageAction):
                message = dispatcher_event.action.message
                if isinstance(message, AssistantMessage):
                    last_ai_message = message
            yield dispatcher_event

        await self._report_conversation_state(
            "deep research",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": last_ai_message,
                "is_new_conversation": self._is_new_conversation,
            },
        )
