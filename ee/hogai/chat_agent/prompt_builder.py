from ee.hogai.chat_agent.prompts import (
    AGENT_PROMPT,
    BASIC_FUNCTIONALITY_PROMPT,
    DOING_TASKS_PROMPT,
    PROACTIVENESS_PROMPT,
    ROLE_PROMPT,
    SWITCHING_MODES_PROMPT,
    TASK_MANAGEMENT_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilderBase
from ee.hogai.utils.prompt import format_prompt_string


class ChatAgentPromptBuilder(AgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        return format_prompt_string(
            AGENT_PROMPT,
            role=ROLE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            proactiveness=PROACTIVENESS_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            doing_tasks=DOING_TASKS_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
        )
