import asyncio
from collections.abc import Awaitable
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from posthog.models import Team, User

from products.tasks.backend.max_tools import (
    CreateTaskTool,
    GetTaskRunLogsTool,
    GetTaskRunTool,
    ListRepositoriesTool,
    ListTaskRunsTool,
    ListTasksTool,
    RunTaskTool,
)

from ee.hogai.chat_agent.prompts import (
    AGENT_CORE_MEMORY_PROMPT,
    AGENT_PROMPT,
    BASIC_FUNCTIONALITY_PROMPT,
    DOING_TASKS_PROMPT,
    PROACTIVENESS_PROMPT,
    ROLE_PROMPT,
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
    ROOT_GROUPS_PROMPT,
    SWITCHING_MODES_PROMPT,
    TASK_MANAGEMENT_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.presets.error_tracking import error_tracking_agent
from ee.hogai.core.agent_modes.presets.product_analytics import product_analytics_agent
from ee.hogai.core.agent_modes.presets.session_replay import session_replay_agent
from ee.hogai.core.agent_modes.presets.sql import sql_agent
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.core.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.registry import get_contextual_tool_class
from ee.hogai.tool import MaxTool
from ee.hogai.tools import (
    CreateFormTool,
    ReadDataTool,
    ReadTaxonomyTool,
    SearchTool,
    SwitchModeTool,
    TaskTool,
    TodoWriteTool,
)
from ee.hogai.utils.feature_flags import (
    has_create_form_tool_feature_flag,
    has_error_tracking_mode_feature_flag,
    has_phai_tasks_feature_flag,
    has_task_tool_feature_flag,
    has_web_search_feature_flag,
)
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, NodePath

DEFAULT_TOOLS: list[type[MaxTool]] = [
    ReadTaxonomyTool,
    ReadDataTool,
    SearchTool,
    TodoWriteTool,
    SwitchModeTool,
]

TASK_TOOLS: list[type["MaxTool"]] = [
    CreateTaskTool,
    RunTaskTool,
    GetTaskRunTool,
    GetTaskRunLogsTool,
    ListTasksTool,
    ListTaskRunsTool,
    ListRepositoriesTool,
]
DEFAULT_CHAT_AGENT_MODE_REGISTRY: dict[AgentMode, AgentModeDefinition] = {
    AgentMode.PRODUCT_ANALYTICS: product_analytics_agent,
    AgentMode.SQL: sql_agent,
    AgentMode.SESSION_REPLAY: session_replay_agent,
}


class ChatAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools = list(DEFAULT_TOOLS)
        if has_create_form_tool_feature_flag(self._team, self._user):
            tools.append(CreateFormTool)
        if has_phai_tasks_feature_flag(self._team, self._user):
            tools.extend(TASK_TOOLS)
        if has_task_tool_feature_flag(self._team, self._user):
            tools.append(TaskTool)
        return tools


class ChatAgentToolkitManager(AgentToolkitManager):
    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list[MaxTool | dict[str, Any]]:
        available_tools = await super().get_tools(state, config)

        tool_names = self._context_manager.get_contextual_tools().keys()
        awaited_contextual_tools: list[Awaitable[MaxTool]] = []
        for tool_name in tool_names:
            ContextualMaxToolClass = get_contextual_tool_class(tool_name)
            if ContextualMaxToolClass is None:
                continue  # Ignoring a tool that the backend doesn't know about - might be a deployment mismatch
            awaited_contextual_tools.append(
                ContextualMaxToolClass.create_tool_class(
                    team=self._team,
                    user=self._user,
                    state=state,
                    config=config,
                    context_manager=self._context_manager,
                )
            )

        contextual_tools = await asyncio.gather(*awaited_contextual_tools)

        # Deduplicate contextual tools
        initialized_tool_names = {tool.get_name() for tool in available_tools if isinstance(tool, MaxTool)}
        for tool in contextual_tools:
            if tool.get_name() not in initialized_tool_names:
                available_tools.append(tool)

        # Final tools = available contextual tools + LLM provider server tools
        if has_web_search_feature_flag(self._team, self._user):
            available_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 5})

        return available_tools


class ChatAgentPromptBuilder(AgentPromptBuilder, AssistantContextMixin):
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        # Add context messages on start of the conversation.
        billing_context_prompt, core_memory, groups = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
        )

        system_prompt = format_prompt_string(
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

        return ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("system", AGENT_CORE_MEMORY_PROMPT),
            ],
            template_format="mustache",
        ).format_messages(
            groups_prompt=f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            billing_context=billing_context_prompt,
            core_memory=format_prompt_string(CORE_MEMORY_PROMPT, core_memory=core_memory),
        )

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


class ChatAgentModeManager(AgentModeManager):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        mode: AgentMode | None = None,
    ):
        super().__init__(team=team, user=user, node_path=node_path, context_manager=context_manager, mode=mode)
        self._mode = mode or AgentMode.PRODUCT_ANALYTICS

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        registry = dict(DEFAULT_CHAT_AGENT_MODE_REGISTRY)
        if has_error_tracking_mode_feature_flag(self._team, self._user):
            registry[AgentMode.ERROR_TRACKING] = error_tracking_agent
        return registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return ChatAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return ChatAgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return ChatAgentToolkitManager
