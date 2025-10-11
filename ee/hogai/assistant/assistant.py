from typing import Any, Optional
from uuid import UUID

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.models import Team, User

from ee.hogai.assistant.base import BaseAssistant
from ee.hogai.assistant.deep_research_assistant import DeepResearchAssistant
from ee.hogai.assistant.insights_assistant import InsightsAssistant
from ee.hogai.assistant.main_assistant import MainAssistant
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.types import AssistantState, PartialAssistantState
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
        new_message: Optional[HumanMessage] = None,
        mode: AssistantMode = AssistantMode.ASSISTANT,
        user: User,
        session_id: Optional[str] = None,
        contextual_tools: Optional[dict[str, Any]] = None,
        is_new_conversation: bool = False,
        trace_id: Optional[str | UUID] = None,
        initial_state: Optional[AssistantMaxGraphState | AssistantMaxPartialGraphState] = None,
        billing_context: Optional[MaxBillingContext] = None,
        deep_research_template: Optional[dict[str, Any]] = None,
    ) -> BaseAssistant:
        if mode == AssistantMode.ASSISTANT:
            assistant_initial_state: Optional[AssistantState | PartialAssistantState] = None
            if initial_state is not None:
                if isinstance(initial_state, (AssistantState | PartialAssistantState)):
                    assistant_initial_state = initial_state
            return MainAssistant(
                team,
                conversation,
                new_message=new_message,
                user=user,
                session_id=session_id,
                contextual_tools=contextual_tools,
                is_new_conversation=is_new_conversation,
                trace_id=trace_id,
                billing_context=billing_context,
                initial_state=assistant_initial_state,
            )
        elif mode == AssistantMode.INSIGHTS_TOOL:
            assistant_initial_state = None
            if initial_state is not None:
                if isinstance(initial_state, (AssistantState | PartialAssistantState)):
                    assistant_initial_state = initial_state
            return InsightsAssistant(
                team,
                conversation,
                new_message=new_message,
                user=user,
                session_id=session_id,
                contextual_tools=contextual_tools,
                is_new_conversation=is_new_conversation,
                trace_id=trace_id,
                billing_context=billing_context,
                initial_state=assistant_initial_state,
            )
        elif mode == AssistantMode.DEEP_RESEARCH:
            deep_research_initial_state: Optional[DeepResearchState | PartialDeepResearchState] = None
            if initial_state is not None:
                if isinstance(initial_state, (DeepResearchState | PartialDeepResearchState)):
                    deep_research_initial_state = initial_state
            return DeepResearchAssistant(
                team,
                conversation,
                new_message=new_message,
                user=user,
                session_id=session_id,
                contextual_tools=contextual_tools,
                is_new_conversation=is_new_conversation,
                trace_id=trace_id,
                billing_context=billing_context,
                initial_state=deep_research_initial_state,
                deep_research_template=deep_research_template,
            )
        else:
            raise ValueError(f"Unknown assistant mode: {mode}")
