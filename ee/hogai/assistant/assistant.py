from typing import Any, Optional
from uuid import UUID

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.models import Team, User

from ee.hogai.assistant.insights_assistant import InsightsAssistant
from ee.hogai.assistant.main_assistant import MainAssistant
from ee.hogai.utils.types.base import AssistantMode
from ee.hogai.utils.types.composed import MaxGraphStateWithMessages, MaxPartialGraphStateWithMessages
from ee.models import Conversation


class Assistant:
    @classmethod
    def create(
        cls,
        team: Team,
        conversation: Conversation,
        *,
        new_message: Optional[HumanMessage] = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        initial_state: Optional[MaxGraphStateWithMessages | MaxPartialGraphStateWithMessages] = None,
        billing_context: Optional[MaxBillingContext] = None,
    ):
        assistant_class = MainAssistant if mode == AssistantMode.ASSISTANT else InsightsAssistant
        return assistant_class(
            team,
            conversation,
            new_message=new_message,
            user=user,
            session_id=session_id,
            contextual_tools=contextual_tools,
            is_new_conversation=is_new_conversation,
            trace_id=trace_id,
            billing_context=billing_context,
            initial_state=initial_state,
        )
