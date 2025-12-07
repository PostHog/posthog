import asyncio
from abc import abstractmethod

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.chat_agent.mode_manager import BillingPromptMixin
from ee.hogai.chat_agent.prompts import (
    ROOT_GROUPS_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes import AgentToolkit
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.presets.product_analytics import ProductAnalyticsAgentToolkit
from ee.hogai.core.agent_modes.presets.session_replay import SessionReplayAgentToolkit
from ee.hogai.core.agent_modes.presets.sql import SQLAgentToolkit
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkitManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.core.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.research_agent.executables import ResearchAgentExecutable, ResearchAgentToolsExecutable
from ee.hogai.research_agent.prompts import (
    BASIC_FUNCTIONALITY_PROMPT,
    ONBOARDING_TASK_PROMPT,
    PLAN_AGENT_PROMPT,
    PLAN_MODE_PROMPT,
    PLANNING_TASK_PROMPT,
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
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, NodePath

RESEARCH_AGENT_MODE_DESCRIPTION_PROMPT = """
Special mode for moving from planning to actually researching data.
Switch to this mode after you have finalized your plan notebook.
"""


class ResearchPlanningAgentToolkit(AgentToolkit):
    pass


research_agent = AgentModeDefinition(
    mode=AgentMode.RESEARCH,
    mode_description=RESEARCH_AGENT_MODE_DESCRIPTION_PROMPT,
    toolkit_class=ResearchPlanningAgentToolkit,
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

DEFAULT_TOOLS = [
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
        return [*DEFAULT_TOOLS, CreateFormTool]


class ResearchAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        return DEFAULT_TOOLS


class ResearchAgentToolkitManager(AgentToolkitManager):
    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list["MaxTool"]:
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
        return available_tools


class PlanAgentSystemPromptBuilderMixin:
    def _get_system_prompt(self):
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


class ResearchAgentSystemPromptBuilderMixin:
    def _get_system_prompt(self):
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


class ResearchAgentPromptBuilderMixin(AgentPromptBuilder, AssistantContextMixin, BillingPromptMixin):
    @abstractmethod
    def _get_system_prompt(self) -> str: ...

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        """
        Get the system prompts for the agent.

        Returns:
            list[BaseMessage]: The system prompts for the agent.
        """

        # Add context messages on start of the conversation.
        core_memory, billing_prompt, groups = await asyncio.gather(
            self._aget_core_memory_text(),
            self._get_billing_prompt(),
            self._context_manager.get_group_names(),
        )

        return ChatPromptTemplate.from_messages(
            [
                ("system", self._get_system_prompt()),
                ("system", CORE_MEMORY_PROMPT),
            ],
            template_format="mustache",
        ).format_messages(
            groups_prompt=f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            core_memory=format_prompt_string(CORE_MEMORY_PROMPT, core_memory=core_memory),
        )


class PlanAgentPromptBuilder(PlanAgentSystemPromptBuilderMixin, ResearchAgentPromptBuilderMixin):
    pass


class ResearchAgentPromptBuilder(ResearchAgentSystemPromptBuilderMixin, ResearchAgentPromptBuilderMixin):
    pass


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
        super().__init__(team=team, user=user, node_path=node_path, context_manager=context_manager, state=state)
        research_mode = state.research_mode
        if not research_mode:
            research_mode = AgentMode.PLAN
        if research_mode not in self.research_mode_registries.keys():
            raise ValueError("Invalid research mode: {research_mode}")
        self._research_mode = research_mode
        self._mode_registry = self.research_mode_registries[self._research_mode]
        self._mode = state.agent_mode or AgentMode.PRODUCT_ANALYTICS

    @property
    def research_mode_registries(self):
        default_mode_registry = {
            AgentMode.PRODUCT_ANALYTICS: research_agent_product_analytics_agent,
            AgentMode.SQL: research_agent_sql_agent,
            AgentMode.SESSION_REPLAY: research_agent_session_replay_agent,
        }
        return {
            AgentMode.PLAN: {**default_mode_registry, AgentMode.RESEARCH: research_agent},
            AgentMode.RESEARCH: default_mode_registry,
        }

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        return self._mode_registry

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return ResearchAgentPromptBuilder if self._research_mode == AgentMode.RESEARCH else PlanAgentPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return ResearchAgentToolkit if self._research_mode == AgentMode.RESEARCH else PlanAgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return ResearchAgentToolkitManager
