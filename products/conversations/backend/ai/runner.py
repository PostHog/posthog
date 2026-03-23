from typing import Optional
from uuid import uuid4

from posthog.schema import AssistantMessage, FailureMessage, HumanMessage

from posthog.models import Team, User

from products.conversations.backend.ai.graph import SupportAgentGraph

from ee.hogai.chat_agent.stream_processor import BaseStreamProcessor
from ee.hogai.core.runner import BaseAgentRunner
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName, ContextMessage
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models import Conversation

SUPPORT_TRIGGER_MESSAGE = "Generate a suggested reply for this support ticket."

STREAMING_NODES: set[MaxNodeName] = {AssistantNodeName.ROOT}
VERBOSE_NODES: set[MaxNodeName] = {AssistantNodeName.ROOT, AssistantNodeName.ROOT_TOOLS}


class SupportAgentRunner(BaseAgentRunner):
    _state: Optional[AssistantState]

    def __init__(
        self,
        team: Team,
        conversation: Conversation,
        *,
        user: User,
        ticket_context: str,
    ):
        self._ticket_context = ticket_context

        super().__init__(
            team,
            conversation,
            new_message=HumanMessage(content=SUPPORT_TRIGGER_MESSAGE),
            user=user,
            graph_class=SupportAgentGraph,
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            use_checkpointer=False,
            is_agent_billable=False,
            stream_processor=BaseStreamProcessor(
                verbose_nodes=VERBOSE_NODES,
                streaming_nodes=STREAMING_NODES,
                state_type=AssistantState,
                team=team,
                user=user,
            ),
        )

    def get_initial_state(self) -> AssistantState:
        context_msg = ContextMessage(content=self._ticket_context, id=str(uuid4()))
        trigger_msg = self._latest_message or HumanMessage(content=SUPPORT_TRIGGER_MESSAGE, id=str(uuid4()))

        return AssistantState(
            messages=[context_msg, trigger_msg],
            start_id=trigger_msg.id,
            query_generation_retry_count=0,
            graph_status=None,
        )

    def get_resumed_state(self) -> PartialAssistantState:
        return PartialAssistantState(messages=[])

    def run(self) -> str:
        """Run the agent synchronously, return the final reply text."""
        results = self.invoke()

        for _, message in reversed(results):
            if isinstance(message, FailureMessage):
                raise ValueError(f"Support agent failed: {message.content or 'unknown error'}")
            if isinstance(message, AssistantMessage) and message.content:
                return message.content.strip()

        raise ValueError("Support agent produced no reply")
