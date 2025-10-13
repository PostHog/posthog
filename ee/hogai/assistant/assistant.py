from typing import Any
from uuid import UUID

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.assistant.deep_research_assistant import DeepResearchAssistant
from ee.hogai.assistant.insights_assistant import InsightsAssistant
from ee.hogai.assistant.main_assistant import MainAssistant
from ee.hogai.utils.types.base import AssistantMode
from ee.hogai.utils.types.composed import AssistantMaxGraphState, AssistantMaxPartialGraphState
from ee.models import Conversation


class Assistant:
    @classmethod
    def create(
        cls,
        team: Team,
        conversation: Conversation,
        *,
        new_message: HumanMessage | None = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        session_id: str | None = None,
        contextual_tools: dict[str, Any] | None = None,
        is_new_conversation: bool = False,
        trace_id: str | UUID | None = None,
        initial_state: AssistantMaxGraphState | AssistantMaxPartialGraphState | None = None,
        billing_context: MaxBillingContext | None = None,
    ) -> BaseAssistant:
        assistant_class: type[BaseAssistant]
        if mode == AssistantMode.ASSISTANT:
            assistant_class = MainAssistant
        elif mode == AssistantMode.INSIGHTS_TOOL:
            assistant_class = InsightsAssistant
        elif mode == AssistantMode.DEEP_RESEARCH:
            assistant_class = DeepResearchAssistant
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
            initial_state=initial_state,  # type: ignore
        )
