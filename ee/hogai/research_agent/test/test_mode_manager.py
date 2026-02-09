from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, HumanMessage

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes import AgentToolkit
from ee.hogai.research_agent.executables import ResearchAgentExecutable, ResearchAgentToolsExecutable
from ee.hogai.research_agent.mode_manager import (
    DEFAULT_TOOLS,
    PlanAgentPromptBuilder,
    PlanAgentToolkit,
    ResearchAgentModeManager,
    ResearchAgentPromptBuilder,
    ResearchAgentToolkit,
    ResearchAgentToolkitManager,
)
from ee.hogai.tools import CreateFormTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath


def _create_mode_manager(team, user, state=None, config=None):
    if state is None:
        state = AssistantState(messages=[HumanMessage(content="Test")])
    if config is None:
        config = RunnableConfig(configurable={})
    node_path = (NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),)
    context_manager = AssistantContextManager(team=team, user=user, config=config)

    return ResearchAgentModeManager(
        team=team,
        user=user,
        node_path=node_path,
        context_manager=context_manager,
        state=state,
    )


class TestResearchAgentModeManager(BaseTest):
    def test_init_defaults_to_plan_mode_when_supermode_not_set(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=None)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager._supermode, AgentMode.PLAN)

    def test_init_with_explicit_plan_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager._supermode, AgentMode.PLAN)

    def test_init_with_explicit_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager._supermode, AgentMode.RESEARCH)

    def test_init_raises_on_invalid_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.SQL)

        with self.assertRaises(ValueError) as context:
            _create_mode_manager(self.team, self.user, state=state)

        self.assertIn("Invalid supermode", str(context.exception))

    def test_init_defaults_agent_mode_to_product_analytics_in_plan_supermode(self):
        """Default mode is PRODUCT_ANALYTICS in PLAN supermode (which is the default supermode)"""
        state = AssistantState(messages=[HumanMessage(content="Test")], agent_mode=None)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager._mode, AgentMode.PRODUCT_ANALYTICS)

    def test_init_preserves_explicit_agent_mode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], agent_mode=AgentMode.SQL)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager._mode, AgentMode.SQL)

    def test_supermode_registries_plan_mode_includes_research(self):
        """PLAN supermode registry includes RESEARCH but not PRODUCT_ANALYTICS"""
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        plan_registry = mode_manager.supermode_registries[AgentMode.PLAN]
        self.assertIn(AgentMode.RESEARCH, plan_registry)
        self.assertIn(AgentMode.PRODUCT_ANALYTICS, plan_registry)  # Now in PLAN mode
        self.assertIn(AgentMode.SQL, plan_registry)
        self.assertIn(AgentMode.SESSION_REPLAY, plan_registry)

    def test_supermode_registries_supermode_excludes_research(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        research_registry = mode_manager.supermode_registries[AgentMode.RESEARCH]
        self.assertNotIn(AgentMode.RESEARCH, research_registry)
        self.assertIn(AgentMode.PRODUCT_ANALYTICS, research_registry)
        self.assertIn(AgentMode.SQL, research_registry)
        self.assertIn(AgentMode.SESSION_REPLAY, research_registry)

    def test_mode_registry_returns_correct_registry_for_plan(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertIn(AgentMode.RESEARCH, mode_manager.mode_registry)

    def test_mode_registry_returns_correct_registry_for_research(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertNotIn(AgentMode.RESEARCH, mode_manager.mode_registry)

    def test_prompt_builder_class_returns_plan_builder_for_plan_mode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager.prompt_builder_class, PlanAgentPromptBuilder)

    def test_prompt_builder_class_returns_research_builder_for_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager.prompt_builder_class, ResearchAgentPromptBuilder)

    def test_toolkit_class_returns_plan_toolkit_for_plan_mode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager.toolkit_class, PlanAgentToolkit)

    def test_toolkit_class_returns_research_toolkit_for_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager.toolkit_class, ResearchAgentToolkit)

    def test_toolkit_manager_class_returns_research_toolkit_manager(self):
        state = AssistantState(messages=[HumanMessage(content="Test")])
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertEqual(mode_manager.toolkit_manager_class, ResearchAgentToolkitManager)

    def test_node_returns_research_agent_executable(self):
        state = AssistantState(messages=[HumanMessage(content="Test")])
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertIsInstance(mode_manager.node, ResearchAgentExecutable)

    def test_tools_node_returns_research_agent_tools_executable(self):
        state = AssistantState(messages=[HumanMessage(content="Test")])
        mode_manager = _create_mode_manager(self.team, self.user, state=state)

        self.assertIsInstance(mode_manager.tools_node, ResearchAgentToolsExecutable)


class TestPlanAgentToolkit(BaseTest):
    def test_tools_includes_create_form_tool(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        toolkit = PlanAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)

        self.assertIn(CreateFormTool, toolkit.tools)

    def test_tools_includes_all_default_tools(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        toolkit = PlanAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)

        for default_tool in DEFAULT_TOOLS:
            self.assertIn(default_tool, toolkit.tools)


class TestResearchAgentToolkit(BaseTest):
    def test_tools_excludes_create_form_tool(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        toolkit = ResearchAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)

        self.assertNotIn(CreateFormTool, toolkit.tools)

    def test_tools_includes_default_tools(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        toolkit = ResearchAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)

        for default_tool in DEFAULT_TOOLS:
            self.assertIn(default_tool, toolkit.tools)


class TestResearchAgentToolkitManager(ClickhouseTestMixin, BaseTest):
    async def test_get_tools_includes_read_data_with_can_read_artifacts(self):
        """Test that ResearchAgentToolkitManager adds ReadDataTool with can_read_artifacts=True"""
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        state = AssistantState(messages=[HumanMessage(content="Test")])

        # Create a minimal toolkit class for testing
        class MinimalToolkit(AgentToolkit):
            @property
            def tools(self):
                return []

        # Configure the toolkit manager with required class attributes
        ResearchAgentToolkitManager.configure(
            agent_toolkit=MinimalToolkit,
            mode_toolkit=MinimalToolkit,
            mode_registry={},
        )

        toolkit_manager = ResearchAgentToolkitManager(
            team=self.team,
            user=self.user,
            context_manager=context_manager,
        )

        with patch(
            "ee.hogai.research_agent.mode_manager.ReadDataTool.create_tool_class", new_callable=AsyncMock
        ) as mock_create:
            mock_tool = AsyncMock()
            mock_create.return_value = mock_tool

            tools = await toolkit_manager.get_tools(state, config)

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            self.assertTrue(call_kwargs["can_read_artifacts"])
            self.assertIn(mock_tool, tools)


class TestPromptBuilders(ClickhouseTestMixin, BaseTest):
    async def test_plan_agent_prompt_builder_get_prompts_returns_messages(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        state = AssistantState(messages=[HumanMessage(content="Test")])

        prompt_builder = PlanAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)

        with (
            patch.object(prompt_builder, "_aget_core_memory_text", new_callable=AsyncMock, return_value="Core memory"),
            patch.object(prompt_builder, "_get_billing_prompt", new_callable=AsyncMock, return_value="Billing prompt"),
            patch.object(context_manager, "get_group_names", new_callable=AsyncMock, return_value=[]),
        ):
            prompts = await prompt_builder.get_prompts(state, config)

            self.assertIsInstance(prompts, list)
            self.assertGreater(len(prompts), 0)

    async def test_research_agent_prompt_builder_get_prompts_returns_messages(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        state = AssistantState(messages=[HumanMessage(content="Test")])

        prompt_builder = ResearchAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)

        with (
            patch.object(prompt_builder, "_aget_core_memory_text", new_callable=AsyncMock, return_value="Core memory"),
            patch.object(prompt_builder, "_get_billing_prompt", new_callable=AsyncMock, return_value="Billing prompt"),
            patch.object(context_manager, "get_group_names", new_callable=AsyncMock, return_value=[]),
        ):
            prompts = await prompt_builder.get_prompts(state, config)

            self.assertIsInstance(prompts, list)
            self.assertGreater(len(prompts), 0)

    async def test_plan_agent_prompt_builder_system_prompt_contains_plan_keywords(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        prompt_builder = PlanAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)
        system_prompt = prompt_builder._get_system_prompt()

        self.assertIn("plan", system_prompt.lower())
        self.assertIn("research", system_prompt.lower())

    async def test_research_agent_prompt_builder_system_prompt_contains_research_keywords(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)

        prompt_builder = ResearchAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)
        system_prompt = prompt_builder._get_system_prompt()

        self.assertIn("research", system_prompt.lower())

    async def test_prompt_builder_includes_groups_when_available(self):
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        state = AssistantState(messages=[HumanMessage(content="Test")])

        prompt_builder = PlanAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)

        with (
            patch.object(prompt_builder, "_aget_core_memory_text", new_callable=AsyncMock, return_value=""),
            patch.object(prompt_builder, "_get_billing_prompt", new_callable=AsyncMock, return_value=""),
            patch.object(context_manager, "get_group_names", new_callable=AsyncMock, return_value=["group1", "group2"]),
        ):
            prompts = await prompt_builder.get_prompts(state, config)

            # Prompts should be generated successfully with groups
            self.assertIsInstance(prompts, list)
            self.assertGreater(len(prompts), 0)
