from collections.abc import Sequence
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from langchain_core.messages import (
    AIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage, MaxBillingContext, MaxBillingContextSubscriptionLevel

from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.core.agent_modes.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.types import AssistantMessageUnion, AssistantState, PartialAssistantState

from .prompts import SUPPORT_SUMMARIZER_SYSTEM_PROMPT, SUPPORT_SUMMARIZER_USER_PROMPT


class TicketCommand(SlashCommand):
    """
    Handles the /ticket slash command.
    Summarizes the conversation for the frontend to use when creating a support ticket.
    """

    _window_manager = AnthropicConversationCompactionManager()

    def _is_organization_new(self) -> bool:
        """Check if the organization was created less than 3 months ago."""
        org_created_at = self._team.organization.created_at
        if not org_created_at:
            return False
        months_since_creation = (timezone.now() - org_created_at).days / 30
        return months_since_creation < 3

    def _can_create_ticket(self, config: RunnableConfig) -> bool:
        """Check if user's subscription allows ticket creation."""
        # Enable ticket creation in local dev
        if settings.DEBUG:
            return True

        if self._is_organization_new():
            return True

        billing_context_data = config.get("configurable", {}).get("billing_context")
        if not billing_context_data:
            return False

        billing_context = MaxBillingContext.model_validate(billing_context_data)

        has_paid_subscription = billing_context.subscription_level in (
            MaxBillingContextSubscriptionLevel.PAID,
            MaxBillingContextSubscriptionLevel.CUSTOM,
        )
        has_active_trial = billing_context.trial is not None and billing_context.trial.is_active

        return has_paid_subscription or has_active_trial

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        if not self._can_create_ticket(config):
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help.",
                        id=str(uuid4()),
                    )
                ]
            )

        if self._is_first_message(state):
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="I'll help you create a support ticket. Please describe your issue below.",
                        id=str(uuid4()),
                    )
                ]
            )

        messages_in_window = self._window_manager.get_messages_in_window(
            state.messages, state.root_conversation_start_id
        )
        summary = await self._summarize_conversation(messages_in_window)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=summary,
                    id=str(uuid4()),
                )
            ]
        )

    def _is_first_message(self, state: AssistantState) -> bool:
        """Check if /ticket is the first message in the conversation."""
        human_messages = [msg for msg in state.messages if isinstance(msg, HumanMessage)]
        return len(human_messages) <= 1

    def _get_model(self) -> MaxChatAnthropic:
        # We are not billing for conversation summary since we would be billing per-ticket creation.
        return MaxChatAnthropic(
            model="claude-haiku-4-5",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            max_tokens=2048,
            billable=False,
        )

    async def _summarize_conversation(self, messages: Sequence[AssistantMessageUnion]) -> str:
        """Summarize the conversation for the support ticket."""
        summarization_header = "PostHog AI Support Ticket Summary"
        messages_list: list[SystemMessage | LangchainHumanMessage | AIMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT)
        ]

        for msg in messages:
            if isinstance(msg, HumanMessage):
                messages_list.append(LangchainHumanMessage(content=msg.content))
            elif isinstance(msg, AssistantMessage) and msg.content:
                messages_list.append(AIMessage(content=msg.content))

        messages_list.append(LangchainHumanMessage(content=SUPPORT_SUMMARIZER_USER_PROMPT))

        response = await self._get_model().ainvoke(messages_list)
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        return f"{summarization_header}:\n\n{content}"
