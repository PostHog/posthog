from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from posthog.models import Organization

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

from posthog.cloud_utils import get_cached_instance_license

from ee.billing.billing_manager import BillingManager
from ee.hogai.chat_agent.slash_commands.commands import SlashCommand
from ee.hogai.core.agent_modes.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.types import AssistantMessageUnion, AssistantState, PartialAssistantState

from .prompts import SUPPORT_SUMMARIZER_SYSTEM_PROMPT, SUPPORT_SUMMARIZER_USER_PROMPT

logger = structlog.get_logger(__name__)


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

    async def _can_create_ticket(self) -> bool:
        """Check if user's subscription allows ticket creation using server-side billing data."""
        if settings.DEBUG:
            return True

        if self._is_organization_new():
            return True

        org = self._team.organization
        if not org.customer_id:
            return False

        try:
            return await sync_to_async(self._check_billing_subscription, thread_sensitive=False)(org)
        except Exception:
            logger.exception("failed_to_fetch_billing_for_ticket_command")
            return False

    def _check_billing_subscription(self, org: Organization) -> bool:
        billing_manager = BillingManager(get_cached_instance_license())
        billing = billing_manager.get_billing(org)
        return billing.get("has_active_subscription", False)

    async def execute(self, config: RunnableConfig, state: AssistantState) -> PartialAssistantState:
        if not await self._can_create_ticket():
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
