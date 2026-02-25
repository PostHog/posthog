from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.chat_agent.prompts import (
    AGENT_CORE_MEMORY_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes import AgentToolkit
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.presets.error_tracking import ErrorTrackingAgentToolkit
from ee.hogai.core.agent_modes.presets.product_analytics import (
    ProductAnalyticsAgentToolkit,
    ReadOnlyProductAnalyticsAgentToolkit,
)
from ee.hogai.core.agent_modes.presets.session_replay import SessionReplayAgentToolkit
from ee.hogai.core.agent_modes.presets.sql import SQLAgentToolkit
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder, AgentPromptBuilderBase
from ee.hogai.core.agent_modes.toolkit import AgentToolkitManager
from ee.hogai.core.plan_mode import ONBOARDING_TASK_PROMPT, PLANNING_TASK_PROMPT
from ee.hogai.research_agent.executables import ResearchAgentExecutable, ResearchAgentToolsExecutable
from ee.hogai.research_agent.prompts import (
    BASIC_FUNCTIONALITY_PROMPT,
    PLAN_AGENT_PROMPT,
    PLAN_MODE_PROMPT,
    REPORT_PROMPT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_MODE_PROMPT,
    RESEARCH_TASK_PROMPT,
    ROLE_PROMPT,
    SWITCHING_MODES_PROMPT,
    SWITCHING_TO_RESEARCH_MODE_PROMPT,
    TASK_MANAGEMENT_PROMPT,
)
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
from ee.hogai.tools.create_notebook.tool import CreateNotebookTool
from ee.hogai.tools.finalize_plan.tool import FinalizePlanTool
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, NodePath

RESEARCH_AGENT_MODE_DESCRIPTION_PROMPT = """
Special mode for moving from planning to actually researching data.
Switch to this mode after you have finalized your plan notebook.
"""


class SwitchToResearchAgentToolkit(AgentToolkit):
    pass


research_agent = AgentModeDefinition(
    mode=AgentMode.RESEARCH,
    mode_description=RESEARCH_AGENT_MODE_DESCRIPTION_PROMPT,
    toolkit_class=SwitchToResearchAgentToolkit,
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

research_agent_product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description="General-purpose mode for product analytics tasks.",
    toolkit_class=ProductAnalyticsAgentToolkit,
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

research_agent_sql_agent = AgentModeDefinition(
    mode=AgentMode.SQL,
    mode_description="SQL mode for researching data.",
    toolkit_class=SQLAgentToolkit,
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

research_agent_session_replay_agent = AgentModeDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description="Session replay mode for researching data.",
    toolkit_class=SessionReplayAgentToolkit,
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

research_agent_error_tracking_agent = AgentModeDefinition(
    mode=AgentMode.ERROR_TRACKING,
    mode_description="Error tracking mode for researching data.",
    toolkit_class=ErrorTrackingAgentToolkit,
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

research_agent_plan_product_analytics_agent = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description="General-purpose mode for product analytics tasks.",
    toolkit_class=ReadOnlyProductAnalyticsAgentToolkit,  # Only CreateInsightTool
    node_class=ResearchAgentExecutable,
    tools_node_class=ResearchAgentToolsExecutable,
)

DEFAULT_TOOLS: list[type["MaxTool"]] = [
    ReadTaxonomyTool,
    SearchTool,
    TodoWriteTool,
    SwitchModeTool,
    CreateNotebookTool,
    TaskTool,
]


class PlanAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [*DEFAULT_TOOLS, CreateFormTool, FinalizePlanTool]


class ResearchAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        return DEFAULT_TOOLS


class ResearchAgentToolkitManager(AgentToolkitManager):
    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list["MaxTool | dict[str, Any]"]:
        available_tools = await super().get_tools(state, config)
        available_tools.append(
            await ReadDataTool.create_tool_class(
                team=self._team,
                user=self._user,
                state=state,
                config=config,
                context_manager=self._context_manager,
                can_read_artifacts=True,
            )
        )
        return list(available_tools)


class ResearchAgentPromptBuilderBase(AgentPromptBuilderBase):
    def _get_core_memory_prompt(self) -> str:
        return AGENT_CORE_MEMORY_PROMPT


class PlanAgentPromptBuilder(ResearchAgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        return format_prompt_string(
            PLAN_AGENT_PROMPT,
            role=ROLE_PROMPT,
            plan_mode=PLAN_MODE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            onboarding_task=ONBOARDING_TASK_PROMPT,
            planning_task=PLANNING_TASK_PROMPT,
            switch_to_research_mode=SWITCHING_TO_RESEARCH_MODE_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
        )


class ResearchAgentPromptBuilder(ResearchAgentPromptBuilderBase):
    def _get_system_prompt(self) -> str:
        return format_prompt_string(
            RESEARCH_AGENT_PROMPT,
            role=ROLE_PROMPT,
            research_mode=RESEARCH_MODE_PROMPT,
            tone_and_style=TONE_AND_STYLE_PROMPT,
            writing_style=WRITING_STYLE_PROMPT,
            basic_functionality=BASIC_FUNCTIONALITY_PROMPT,
            switching_modes=SWITCHING_MODES_PROMPT,
            task_management=TASK_MANAGEMENT_PROMPT,
            research_task=RESEARCH_TASK_PROMPT,
            report=REPORT_PROMPT,
            tool_usage_policy=TOOL_USAGE_POLICY_PROMPT,
        )


class ResearchAgentModeManager(AgentModeManager):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        state: AssistantState,
    ):
        # Set _supermode and _mode_registry before super().__init__() because
        # the parent's __init__ accesses self.mode_registry
        supermode = state.supermode
        if not supermode:
            supermode = AgentMode.PLAN
        if supermode not in self.supermode_registries.keys():
            raise ValueError(f"Invalid supermode: {supermode}")
        self._supermode = cast(AgentMode, supermode)
        self._mode_registry = self.supermode_registries[self._supermode]
        self._mode = (
            state.agent_mode
            if state.agent_mode and state.agent_mode in self.mode_registry
            else AgentMode.PRODUCT_ANALYTICS
        )
        super().__init__(team=team, user=user, node_path=node_path, context_manager=context_manager, state=state)

    @property
    def supermode_registries(self):
        default_mode_registry = {
            AgentMode.SQL: research_agent_sql_agent,
            AgentMode.SESSION_REPLAY: research_agent_session_replay_agent,
            AgentMode.ERROR_TRACKING: research_agent_error_tracking_agent,
        }
        return {
            AgentMode.PLAN: {
                **default_mode_registry,
                AgentMode.RESEARCH: research_agent,
                AgentMode.PRODUCT_ANALYTICS: research_agent_plan_product_analytics_agent,
            },
            AgentMode.RESEARCH: {
                **default_mode_registry,
                AgentMode.PRODUCT_ANALYTICS: research_agent_product_analytics_agent,
            },
        }

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        return self._mode_registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return ResearchAgentPromptBuilder if self._supermode == AgentMode.RESEARCH else PlanAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return ResearchAgentToolkit if self._supermode == AgentMode.RESEARCH else PlanAgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return ResearchAgentToolkitManager
