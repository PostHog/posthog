from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantTool,
    AssistantToolCall,
    AssistantToolCallMessage,
    HumanMessage,
)

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.executables import AgentExecutable, AgentToolsExecutable
from ee.hogai.research_agent.executables import ResearchAgentExecutable
from ee.hogai.research_agent.mode_manager import ResearchAgentModeManager
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath


def _create_research_agent_node(
    team: Team,
    user: User,
    *,
    state: AssistantState | None = None,
    node_path: tuple[NodePath, ...] | None = None,
    config: RunnableConfig | None = None,
):
    if node_path is None:
        node_path = (NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),)
    if state is None:
        state = AssistantState(messages=[HumanMessage(content="Test")])

    config = config or RunnableConfig(configurable={})
    context_manager = AssistantContextManager(team=team, user=user, config=config)
    mode_manager = ResearchAgentModeManager(
        team=team,
        user=user,
        node_path=node_path,
        context_manager=context_manager,
        state=state,
    )
    node = mode_manager.node
    node._config = config
    node._context_manager = context_manager
    return node


def _create_research_agent_tools_node(
    team: Team,
    user: User,
    *,
    state: AssistantState | None = None,
    node_path: tuple[NodePath, ...] | None = None,
    config: RunnableConfig | None = None,
):
    if node_path is None:
        node_path = (NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),)
    if state is None:
        state = AssistantState(messages=[HumanMessage(content="Test")])

    config = config or RunnableConfig(configurable={})
    context_manager = AssistantContextManager(team=team, user=user, config=config)
    mode_manager = ResearchAgentModeManager(
        team=team,
        user=user,
        node_path=node_path,
        context_manager=context_manager,
        state=state,
    )
    node = mode_manager.tools_node
    node._config = config
    node._context_manager = context_manager
    return node


class TestResearchAgentExecutable(ClickhouseTestMixin, BaseTest):
    def test_max_tool_calls_is_high(self):
        self.assertEqual(ResearchAgentExecutable.MAX_TOOL_CALLS, 1_000_000)

    def test_max_tokens_config(self):
        self.assertEqual(ResearchAgentExecutable.MAX_TOKENS, 16_384)

    def test_thinking_config(self):
        self.assertEqual(
            ResearchAgentExecutable.THINKING_CONFIG,
            {"type": "enabled", "budget_tokens": 4096},
        )

    async def test_arun_sets_supermode_and_agent_mode(self):
        """Test that arun modifies state correctly before calling parent"""
        state = AssistantState(messages=[HumanMessage(content="Test")])
        node = _create_research_agent_node(self.team, self.user, state=state)

        # Mock the parent arun to capture the state it receives
        captured_state = None

        async def mock_parent_arun(self_node, new_state, config):
            nonlocal captured_state
            captured_state = new_state
            return PartialAssistantState(
                messages=[AssistantMessage(content="Response")],
                supermode=new_state.supermode,
                agent_mode=new_state.agent_mode,
            )

        with patch.object(AgentExecutable, "arun", new=mock_parent_arun):
            await node.arun(state, {})

            self.assertIsNotNone(captured_state)
            assert captured_state is not None  # for mypy
            self.assertEqual(captured_state.supermode, AgentMode.PLAN)
            self.assertEqual(captured_state.agent_mode, AgentMode.SQL)  # Plan mode defaults to SQL

    async def test_arun_preserves_supermode_when_not_human_message(self):
        """Test that supermode is preserved when last message is not HumanMessage"""
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ],
            supermode=AgentMode.RESEARCH,
            agent_mode=AgentMode.SQL,
        )
        node = _create_research_agent_node(self.team, self.user, state=state)

        captured_state = None

        async def mock_parent_arun(self_node, new_state, config):
            nonlocal captured_state
            captured_state = new_state
            return PartialAssistantState(messages=[AssistantMessage(content="Response")])

        with patch.object(AgentExecutable, "arun", new=mock_parent_arun):
            await node.arun(state, {})

            # When last message is not HumanMessage and supermode is set,
            # the mode should be preserved
            self.assertIsNotNone(captured_state)
            assert captured_state is not None  # for mypy
            self.assertEqual(captured_state.supermode, AgentMode.RESEARCH)

    async def test_get_model_uses_claude_opus_with_thinking(self):
        state = AssistantState(messages=[HumanMessage(content="Test")])
        node = _create_research_agent_node(self.team, self.user, state=state)

        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        with patch("ee.hogai.research_agent.executables.MaxChatAnthropic", return_value=mock_model) as mock_anthropic:
            node._get_model(state, [])

            mock_anthropic.assert_called_once()
            call_kwargs = mock_anthropic.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "claude-opus-4-5-20251101")
            self.assertEqual(call_kwargs["max_tokens"], 16_384)
            self.assertEqual(call_kwargs["thinking"], {"type": "enabled", "budget_tokens": 4096})
            self.assertTrue(call_kwargs["streaming"])
            self.assertTrue(call_kwargs["billable"])
            self.assertIn("interleaved-thinking-2025-05-14", call_kwargs["betas"])

    async def test_get_model_binds_tools_with_parallel_calls(self):
        state = AssistantState(messages=[HumanMessage(content="Test")])
        node = _create_research_agent_node(self.team, self.user, state=state)

        mock_model = MagicMock()
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        with patch("ee.hogai.research_agent.executables.MaxChatAnthropic", return_value=mock_model):
            node._get_model(state, [])

            mock_model.bind_tools.assert_called_once()
            call_kwargs = mock_model.bind_tools.call_args.kwargs
            self.assertTrue(call_kwargs["parallel_tool_calls"])

    def test_should_transition_is_not_on_root_executable(self):
        """Transition logic lives on the tools executable, not the root executable."""
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        node = _create_research_agent_node(self.team, self.user, state=state)
        self.assertFalse(hasattr(node, "_should_transition"))


class TestResearchAgentToolsExecutable(ClickhouseTestMixin, BaseTest):
    async def test_arun_transitions_to_research_supermode_when_switch_mode_called(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="Test"),
                AssistantMessage(
                    content="Switching mode",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="tool-1",
                            name="switch_mode",
                            args={"new_mode": "research"},
                        )
                    ],
                ),
            ],
            supermode=AgentMode.PLAN,
            root_tool_call_id="tool-1",
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        async def mock_parent_arun(self_node, new_state, config):
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(content="Switched", id="tool-msg-1", tool_call_id="tool-1"),
                ],
                agent_mode=AgentMode.RESEARCH,
            )

        with patch.object(AgentToolsExecutable, "arun", new=mock_parent_arun):
            result = await node.arun(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(result.agent_mode, AgentMode.PRODUCT_ANALYTICS)
            self.assertEqual(result.supermode, AgentMode.RESEARCH)

    async def test_arun_does_not_transition_when_not_in_plan_supermode(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(
                    content="Switching mode",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="tool-1",
                            name="switch_mode",
                            args={"new_mode": "research"},
                        )
                    ],
                ),
            ],
            supermode=AgentMode.RESEARCH,
            root_tool_call_id="tool-1",
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        async def mock_parent_arun(self_node, new_state, config):
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(content="Result", id="tool-msg-1", tool_call_id="tool-1"),
                ],
                agent_mode=AgentMode.RESEARCH,
            )

        with patch.object(AgentToolsExecutable, "arun", new=mock_parent_arun):
            result = await node.arun(state, {})

            self.assertIsNone(result.supermode)

    def test_should_transition_returns_true_when_in_plan_supermode_and_agent_mode_is_research(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        result = PartialAssistantState(agent_mode=AgentMode.RESEARCH)
        node = _create_research_agent_tools_node(self.team, self.user, state=state)
        self.assertTrue(node._should_transition(state, result))

    def test_should_transition_returns_false_when_not_in_plan_supermode(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.RESEARCH)
        result = PartialAssistantState(agent_mode=AgentMode.RESEARCH)
        node = _create_research_agent_tools_node(self.team, self.user, state=state)
        self.assertFalse(node._should_transition(state, result))

    def test_should_transition_returns_false_when_agent_mode_is_not_research(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        result = PartialAssistantState(agent_mode=AgentMode.SQL)
        node = _create_research_agent_tools_node(self.team, self.user, state=state)
        self.assertFalse(node._should_transition(state, result))

    def test_should_transition_returns_false_when_agent_mode_is_none(self):
        state = AssistantState(messages=[HumanMessage(content="Test")], supermode=AgentMode.PLAN)
        result = PartialAssistantState(agent_mode=None)
        node = _create_research_agent_tools_node(self.team, self.user, state=state)
        self.assertFalse(node._should_transition(state, result))

    def test_router_returns_end_on_final_notebook_with_content(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(
                    content="Creating final notebook",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name=AssistantTool.CREATE_NOTEBOOK,
                            args={"content": "# Final Report\nThis is the final report."},
                        )
                    ],
                ),
                AssistantToolCallMessage(content="Notebook created", tool_call_id="xyz"),
            ],
            supermode=AgentMode.RESEARCH,
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        result = node.router(state)

        # With the new approval flow, notebook creation doesn't end the conversation
        # The agent must ask for approval via create_form, then use switch_mode
        self.assertEqual(result, "root")

    def test_router_returns_root_on_draft_notebook(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(
                    content="Creating draft notebook",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name=AssistantTool.CREATE_NOTEBOOK,
                            args={"draft_content": "# Draft\nWork in progress"},
                        )
                    ],
                ),
                AssistantToolCallMessage(content="Draft saved", tool_call_id="xyz"),
            ],
            supermode=AgentMode.RESEARCH,
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        result = node.router(state)

        self.assertEqual(result, "root")

    def test_router_returns_root_when_not_in_supermode(self):
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(
                    content="Creating notebook",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name=AssistantTool.CREATE_NOTEBOOK,
                            args={"content": "# Final Report"},
                        )
                    ],
                ),
                AssistantToolCallMessage(content="Notebook created", tool_call_id="xyz"),
            ],
            supermode=AgentMode.PLAN,
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        result = node.router(state)

        self.assertEqual(result, "root")

    def test_router_returns_root_when_no_notebook_tool_call(self):
        """When there's no CREATE_NOTEBOOK tool call, router should return 'root'"""
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(
                    content="Reading data",
                    id="msg-1",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name=AssistantTool.READ_TAXONOMY,
                            args={"query": {"kind": "events"}},
                        )
                    ],
                ),
                AssistantToolCallMessage(content="Data read", tool_call_id="xyz"),
            ],
            supermode=AgentMode.RESEARCH,
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        result = node.router(state)
        self.assertEqual(result, "root")

    def test_router_returns_end_when_last_message_not_tool_call(self):
        """When the last message is not a tool call, the conversation ends."""
        state = AssistantState(
            messages=[
                HumanMessage(content="Research this"),
                AssistantMessage(content="Here is my response"),
            ],
            supermode=AgentMode.RESEARCH,
        )
        node = _create_research_agent_tools_node(self.team, self.user, state=state)

        result = node.router(state)

        self.assertEqual(result, "end")
