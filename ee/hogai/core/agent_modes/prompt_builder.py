import asyncio
from abc import ABC, abstractmethod
from typing import Generic

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.core.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, StateType

ROOT_GROUPS_PROMPT = """
<groups>
The user has defined the following groups: {{{groups}}}.
</groups>
""".strip()

ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT = """
<billing_context>
If the user asks about billing, their subscription, their usage, or their spending, use the `read_data` tool with the `billing_info` kind to answer.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
</billing_context>
""".strip()

ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT = """
<billing_context>
The user does not have admin access to view detailed billing information. They would need to contact an organization admin for billing details.
In case the user asks to debug problems that relate to billing, suggest them to contact an admin.
</billing_context>
""".strip()

ROOT_BILLING_CONTEXT_ERROR_PROMPT = """
<billing_context>
If the user asks about billing, their subscription, their usage, or their spending, suggest them to talk to PostHog support.
</billing_context>
""".strip()


class PromptBuilder(ABC, Generic[StateType]):
    @abstractmethod
    async def get_prompts(self, state: StateType, config: RunnableConfig) -> list[BaseMessage]: ...


class AgentPromptBuilder(PromptBuilder[AssistantState]):
    def __init__(self, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @abstractmethod
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]: ...


class BillingPromptMixin:
    _context_manager: AssistantContextManager

    async def _get_billing_prompt(self) -> str:
        """Get billing information including whether to include the billing tool and the prompt.
        Returns:
            str: prompt
        """
        has_billing_context = self._context_manager.get_billing_context() is not None
        has_access = await self._context_manager.check_user_has_billing_access()

        if has_access and not has_billing_context:
            return ROOT_BILLING_CONTEXT_ERROR_PROMPT

        prompt = (
            ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
            if has_access and has_billing_context
            else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
        )
        return prompt


class AgentPromptBuilderBase(AgentPromptBuilder, AssistantContextMixin, BillingPromptMixin):
    """Base class for agent prompt builders with shared logic for gathering context."""

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Return the formatted system prompt. Must be implemented by subclasses."""
        ...

    def _get_core_memory_prompt(self) -> str:
        """Return the core memory prompt template. Override in subclasses if needed."""
        return CORE_MEMORY_PROMPT

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        billing_prompt, core_memory, groups = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
        )

        format_args = {
            "groups_prompt": f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            "core_memory": core_memory,
            "billing_context": billing_prompt,
        }

        return ChatPromptTemplate.from_messages(
            [
                ("system", self._get_system_prompt()),
                ("system", self._get_core_memory_prompt()),
            ],
            template_format="mustache",
        ).format_messages(**format_args)
