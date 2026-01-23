import asyncio
from collections.abc import Awaitable
from typing import Any

from langchain_core.runnables import RunnableConfig

from products.tasks.backend.max_tools import (
    CreateTaskTool,
    GetTaskRunLogsTool,
    GetTaskRunTool,
    ListRepositoriesTool,
    ListTaskRunsTool,
    ListTasksTool,
    RunTaskTool,
)

from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.registry import get_contextual_tool_class
from ee.hogai.tool import MaxTool
from ee.hogai.tools import (
    CreateFormTool,
    ListDataTool,
    ManageMemoriesTool,
    ReadDataTool,
    ReadTaxonomyTool,
    SearchTool,
    SwitchModeTool,
    TaskTool,
    TodoWriteTool,
)
from ee.hogai.tools.finalize_plan.tool import FinalizePlanTool
from ee.hogai.utils.feature_flags import (
    has_create_form_tool_feature_flag,
    has_memory_tool_feature_flag,
    has_phai_tasks_feature_flag,
    has_task_tool_feature_flag,
    has_web_search_feature_flag,
)
from ee.hogai.utils.types.base import AssistantState

DEFAULT_TOOLS: list[type[MaxTool]] = [
    ReadTaxonomyTool,
    ReadDataTool,
    SearchTool,
    ListDataTool,
    TodoWriteTool,
    SwitchModeTool,
]

TASK_TOOLS: list[type[MaxTool]] = [
    CreateTaskTool,
    RunTaskTool,
    GetTaskRunTool,
    GetTaskRunLogsTool,
    ListTasksTool,
    ListTaskRunsTool,
    ListRepositoriesTool,
]


class ChatAgentPlanToolkit(AgentToolkit):
    """Agent toolkit for plan mode with base tools + plan-specific tools."""

    @property
    def tools(self) -> list[type[MaxTool]]:
        tools = [
            ReadTaxonomyTool,
            SearchTool,
            TodoWriteTool,  # type: ignore[list-item]
            SwitchModeTool,  # type: ignore[list-item]
            CreateFormTool,
            FinalizePlanTool,
        ]
        if has_memory_tool_feature_flag(self._team, self._user):
            tools.append(ManageMemoriesTool)
        return tools


class ChatAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type[MaxTool]]:
        tools = list(DEFAULT_TOOLS)
        if has_phai_tasks_feature_flag(self._team, self._user):
            tools.extend(TASK_TOOLS)
        if has_task_tool_feature_flag(self._team, self._user):
            tools.append(TaskTool)
        if has_memory_tool_feature_flag(self._team, self._user):
            tools.append(ManageMemoriesTool)
        if has_create_form_tool_feature_flag(self._team, self._user):
            tools.append(CreateFormTool)
        return tools


class PlanModeSwitchAgentToolkit(AgentToolkit):
    """Empty toolkit for the fictitious execution/plan modes that triggers transition to execution/plan mode."""

    pass


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
