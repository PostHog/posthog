import asyncio

from asgiref.sync import sync_to_async
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from products.business_knowledge.backend.facade import api as business_knowledge_api
from products.conversations.backend.ai.prompts import (
    SUPPORT_RESPONSE_FORMAT_PROMPT,
    SUPPORT_ROLE_PROMPT,
    SUPPORT_SAFETY_PROMPT,
    SUPPORT_SYSTEM_PROMPT,
    SUPPORT_TONE_PROMPT,
    SUPPORT_TOOL_USAGE_PROMPT,
)

from ee.hogai.core.agent_modes.prompt_builder import ROOT_GROUPS_PROMPT, AgentPromptBuilderBase
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState


class SupportAgentPromptBuilder(AgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        return format_prompt_string(
            SUPPORT_SYSTEM_PROMPT,
            role=SUPPORT_ROLE_PROMPT,
            tone=SUPPORT_TONE_PROMPT,
            tool_usage=SUPPORT_TOOL_USAGE_PROMPT,
            safety=SUPPORT_SAFETY_PROMPT,
            response_format=SUPPORT_RESPONSE_FORMAT_PROMPT,
        )

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        # Mirror the base class' async gather so the knowledge lookup (a tiny
        # Postgres query) piggybacks on the same round-trip instead of adding
        # serial latency to every ticket turn.
        billing_prompt, core_memory, groups, knowledge_section = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
            sync_to_async(business_knowledge_api.format_knowledge_prompt)(self._team.id),
        )

        format_args = {
            "groups_prompt": f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            "core_memory": core_memory,
            "billing_context": billing_prompt,
        }

        messages: list[tuple[str, str]] = [
            ("system", self._get_system_prompt()),
            ("system", self._get_core_memory_prompt()),
        ]
        # Only inject a knowledge system message when the team actually has
        # ready sources. An empty prompt fragment would otherwise burn tokens
        # and nudge the model toward hallucinating citations.
        if knowledge_section.has_knowledge:
            messages.append(("system", knowledge_section.prompt))

        return ChatPromptTemplate.from_messages(messages, template_format="mustache").format_messages(**format_args)
