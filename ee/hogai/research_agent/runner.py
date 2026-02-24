from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import posthoganalytics

from posthog.schema import AgentMode, AssistantMessage, HumanMessage, MaxBillingContext

from posthog import event_usage
from posthog.models import Team, User

from ee.hogai.chat_agent.stream_processor import ChatAgentStreamProcessor
from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.research_agent.graph import ResearchAgentGraph
from ee.hogai.utils.types import AssistantOutput
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState, PartialAssistantState
from ee.models import Conversation

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


STREAMING_NODES: set["MaxNodeName"] = {
    AssistantNodeName.ROOT,
}

VERBOSE_NODES: set["MaxNodeName"] = STREAMING_NODES | {
    AssistantNodeName.ROOT,
    AssistantNodeName.ROOT_TOOLS,
    AssistantNodeName.TRENDS_GENERATOR,
    AssistantNodeName.FUNNEL_GENERATOR,
    AssistantNodeName.RETENTION_GENERATOR,
    AssistantNodeName.SQL_GENERATOR,
    AssistantNodeName.INSIGHTS_SEARCH,
    AssistantNodeName.QUERY_EXECUTOR,
}


class ResearchAgentRunner(BaseAgentRunner):
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
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        billing_context: Optional[MaxBillingContext] = None,
        initial_state: Optional[AssistantState | PartialAssistantState] = None,
        is_agent_billable: bool = True,
        is_impersonated: bool = False,
        resume_payload: Optional[dict[str, Any]] = None,
    ):
        super().__init__(
            team,
            conversation,
            new_message=new_message,
            user=user,
            graph_class=ResearchAgentGraph,
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            session_id=session_id,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
            use_checkpointer=True,
            is_agent_billable=is_agent_billable,
            is_impersonated=is_impersonated,
            stream_processor=ChatAgentStreamProcessor(
                team=team,
                user=user,
                verbose_nodes=VERBOSE_NODES,
                streaming_nodes=STREAMING_NODES,
                state_type=AssistantState,
            ),
            resume_payload=resume_payload,
        )

    def get_initial_state(self) -> AssistantState:
        if self._latest_message:
            return AssistantState(
                messages=[self._latest_message],
                start_id=self._latest_message.id,
                graph_status=None,
                supermode=AgentMode.PLAN,
                agent_mode=AgentMode.SQL,
            )
        else:
            return AssistantState(messages=[])

    def get_resumed_state(self) -> PartialAssistantState:
        if not self._latest_message:
            return PartialAssistantState(messages=[])
        return PartialAssistantState(messages=[self._latest_message], graph_status="resumed")

    async def astream(
        self,
        stream_message_chunks: bool = True,
        stream_subgraphs: bool = True,
        stream_first_message: bool = True,
        stream_only_assistant_messages: bool = False,
    ) -> AsyncGenerator[AssistantOutput, None]:
        if self._user:
            posthoganalytics.capture(
                distinct_id=self._user.distinct_id,
                event="ai deep research executed",
                properties={
                    "conversation_id": str(self._conversation.id),
                    "is_new_conversation": self._is_new_conversation,
                    "$session_id": self._session_id,
                },
                groups=event_usage.groups(team=self._team),
            )

        last_ai_message: AssistantMessage | None = None
        async for stream_event in super().astream(
            stream_message_chunks, stream_subgraphs, stream_first_message, stream_only_assistant_messages
        ):
            _, message = stream_event
            if isinstance(message, AssistantMessage):
                last_ai_message = message
            yield stream_event

        await self._report_conversation_state(
            "deep research",
            {
                "prompt": self._latest_message.content if self._latest_message else None,
                "output": last_ai_message,
                "is_new_conversation": self._is_new_conversation,
            },
        )
