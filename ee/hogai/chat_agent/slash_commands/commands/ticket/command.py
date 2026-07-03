from collections.abc import Sequence
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from asgiref.sync import sync_to_async
from langchain_core.messages import (
    AIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

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

    async def _is_organization_new(self) -> bool:
        """Check if the organization was created less than 3 months ago."""
        # `self._team.organization` is a FK access that hits the DB when not prefetched,
        # so it must be wrapped to be safe inside this async context.
        org_created_at = await sync_to_async(lambda: self._team.organization.created_at)()
        if not org_created_at:
            return False
        months_since_creation = (timezone.now() - org_created_at).days / 30
        return months_since_creation < 3

    async def _can_create_ticket(self) -> bool:
        """Check if the organization's subscription allows ticket creation."""
        # Enable ticket creation in local dev
        if settings.DEBUG:
            return True

        if await self._is_organization_new():
            return True

        return await self._has_paid_plan_or_active_trial()

    async def _has_paid_plan_or_active_trial(self) -> bool:
        """
        Check the plan tier derived from the organization's synced billing entitlements.

        `available_product_features` is kept up to date by every billing load, and active
        trials grant the trial plan's features, so a non-free tier means a paid or custom
        subscription or an active trial. Reading it locally keeps the slow billing service
        API out of the conversation turn. Organizations with no synced entitlements are
        denied, so missing data fails closed.
        """
        # `self._team.organization` is a FK access that hits the DB when not prefetched,
        # so it must be wrapped to be safe inside this async context.
        return await sync_to_async(lambda: self._team.organization.get_plan_tier() != "free")()

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        if not await self._can_create_ticket():
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help. If your issue is about billing, you can always contact our support team through the in-app help panel.",
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
