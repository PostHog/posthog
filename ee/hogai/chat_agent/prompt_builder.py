import asyncio

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.chat_agent.prompts import (
    AGENT_PROMPT,
    BASIC_FUNCTIONALITY_PROMPT,
    DOING_TASKS_PROMPT,
    PROACTIVENESS_PROMPT,
    PRODUCT_ADVOCACY_PROMPT,
    ROLE_PROMPT,
    SWITCHING_MODES_PROMPT,
    SWITCHING_TO_PLAN_PROMPT,
    TASK_MANAGEMENT_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.chat_agent.prompts.plan import (
    CHAT_ONBOARDING_TASK_PROMPT,
    CHAT_PLAN_AGENT_PROMPT,
    CHAT_PLAN_MODE_PROMPT,
    SWITCHING_TO_EXECUTION_PROMPT,
)
from ee.hogai.chat_agent.toolkit import DEFAULT_TOOLS
from ee.hogai.core.agent_modes.prompt_builder import ROOT_GROUPS_PROMPT, AgentPromptBuilderBase
from ee.hogai.core.plan_mode import EXECUTION_CAPABILITIES_PROMPT, PLANNING_TASK_PROMPT
from ee.hogai.tools.switch_mode import _get_default_tools_prompt, _get_modes_prompt
from ee.hogai.utils.feature_flags import has_plan_mode_feature_flag
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState


class ChatAgentPlanPromptBuilder(AgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        """This method is unused in this class since get_prompts is overridden."""
        return ""

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        from ee.hogai.chat_agent.mode_manager import get_execution_mode_registry  # circular import

        execution_registry = get_execution_mode_registry(self._team, self._user)

        billing_prompt, core_memory, groups, default_tools, available_modes = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
            _get_default_tools_prompt(
                team=self._team,
                user=self._user,
                state=state,
                config=config,
                default_tool_classes=DEFAULT_TOOLS,
            ),
            _get_modes_prompt(
                team=self._team,
                user=self._user,
                state=state,
                config=config,
                context_manager=self._context_manager,
                mode_registry=execution_registry,
            ),
        )

        execution_capabilities = format_prompt_string(
            EXECUTION_CAPABILITIES_PROMPT,
            default_tools=default_tools,
            available_modes=available_modes,
        )

        system_prompt = format_prompt_string(
            CHAT_PLAN_AGENT_PROMPT,
            role=ROLE_PROMPT,
            plan_mode=CHAT_PLAN_MODE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            onboarding_task=CHAT_ONBOARDING_TASK_PROMPT,
            planning_task=PLANNING_TASK_PROMPT,
            product_advocacy=PRODUCT_ADVOCACY_PROMPT,
            switch_to_execution=SWITCHING_TO_EXECUTION_PROMPT,
            execution_capabilities=execution_capabilities,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
        )

        format_args = {
            "groups_prompt": f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            "core_memory": core_memory,
            "billing_context": billing_prompt,
        }

        return ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("system", self._get_core_memory_prompt()),
            ],
            template_format="mustache",
        ).format_messages(**format_args)


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
            product_advocacy=PRODUCT_ADVOCACY_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
            switching_to_plan=switching_to_plan,
        )
