from products.conversations.backend.ai.prompts import (
    SUPPORT_RESPONSE_FORMAT_PROMPT,
    SUPPORT_ROLE_PROMPT,
    SUPPORT_SAFETY_PROMPT,
    SUPPORT_SYSTEM_PROMPT,
    SUPPORT_TONE_PROMPT,
    SUPPORT_TOOL_USAGE_PROMPT,
)

from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilderBase
from ee.hogai.utils.prompt import format_prompt_string


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
