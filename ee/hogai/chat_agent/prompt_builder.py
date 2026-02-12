from ee.hogai.chat_agent.prompts import (
    AGENT_PROMPT,
    BASIC_FUNCTIONALITY_PROMPT,
    DOING_TASKS_PROMPT,
    PROACTIVENESS_PROMPT,
    ROLE_PROMPT,
    SWITCHING_MODES_PROMPT,
    SWITCHING_TO_PLAN_PROMPT,
    TASK_MANAGEMENT_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.chat_agent.prompts.plan import (
    CHAT_PLAN_AGENT_PROMPT,
    CHAT_PLAN_MODE_PROMPT,
    SWITCHING_TO_EXECUTION_PROMPT,
)
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilderBase
from ee.hogai.core.plan_mode import ONBOARDING_TASK_PROMPT, PLANNING_TASK_PROMPT
from ee.hogai.utils.feature_flags import has_plan_mode_feature_flag
from ee.hogai.utils.prompt import format_prompt_string


class ChatAgentPlanPromptBuilder(AgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        return format_prompt_string(
            CHAT_PLAN_AGENT_PROMPT,
            role=ROLE_PROMPT,
            plan_mode=CHAT_PLAN_MODE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            onboarding_task=ONBOARDING_TASK_PROMPT,
            planning_task=PLANNING_TASK_PROMPT,
            switch_to_execution=SWITCHING_TO_EXECUTION_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
        )


class ChatAgentPromptBuilder(AgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        if has_plan_mode_feature_flag(self._team, self._user):
            switching_to_plan = SWITCHING_TO_PLAN_PROMPT
        else:
            switching_to_plan = ""
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
            switching_to_plan=switching_to_plan,
        )
