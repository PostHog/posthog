import datetime
from contextlib import contextmanager

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AIMessage as LangchainAIMessage,
    SystemMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    HumanMessage,
    MaxBillingContext,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
)

from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership

from ee.hogai.chat_agent.mode_manager import ChatAgentModeManager, ChatAgentPromptBuilder, ChatAgentToolkit
from ee.hogai.chat_agent.prompts import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool
from ee.hogai.utils.tests import FakeChatAnthropic, FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath


@contextmanager
def mock_contextual_tool(mock_tool):
    """Helper to mock a contextual tool class with create_tool_class"""
    mock_tool_class = MagicMock()
    mock_tool_class.create_tool_class = AsyncMock(return_value=mock_tool)

    with patch("ee.hogai.registry.get_contextual_tool_class", return_value=mock_tool_class):
        yield


def _create_agent_node(
    team: Team,
    user: User,
    *,
    node_path: tuple[NodePath, ...] | None = None,
    config: RunnableConfig | None = None,
):
    if node_path is None:
        node_path = (NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),)
    context_manager = AssistantContextManager(team=team, user=user, config=config or RunnableConfig(configurable={}))
    mode_manager = ChatAgentModeManager(team=team, user=user, node_path=node_path, context_manager=context_manager)
    node = mode_manager.node
    # Set the node's config and context_manager to use the one with the config
    node._config = config or RunnableConfig(configurable={})
    node._context_manager = context_manager
    return node


def _create_agent_tools_node(
    team: Team,
    user: User,
    *,
    node_path: tuple[NodePath, ...] | None = None,
    config: RunnableConfig | None = None,
):
    if node_path is None:
        node_path = (NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),)

    context_manager = AssistantContextManager(team=team, user=user, config=config or RunnableConfig(configurable={}))
    mode_manager = ChatAgentModeManager(team=team, user=user, node_path=node_path, context_manager=context_manager)
    node = mode_manager.tools_node
    # Set the node's config and context_manager to use the one with the config
    node._config = config or RunnableConfig(configurable={})
    node._context_manager = context_manager
    return node


class TestAgentToolkit(BaseTest):
    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch("ee.hogai.registry.get_contextual_tool_class")
    async def test_get_tools_ignores_unknown_contextual_tools(self, mock_get_tool_class, mock_model):
        """Test that unknown contextual tools (None from get_contextual_tool_class) are ignored"""
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])
        mock_get_tool_class.return_value = None  # Simulates unknown tool

        state = AssistantState(messages=[HumanMessage(content="Test")])
        config = RunnableConfig(configurable={"contextual_tools": {"unknown_tool": {"some": "config"}}})
        node = _create_agent_node(self.team, self.user, config=config)

        # Should not raise an error, just skip the unknown tool
        result = await node.arun(state, config)
        self.assertIsNotNone(result)

    @parameterized.expand(
        [
            # (create_form_flag, tasks_flag, expected_tools, unexpected_tools)
            [
                False,
                False,
                ["read_taxonomy", "read_data", "search", "todo_write", "switch_mode"],
                ["create_form", "create_task", "run_task", "list_tasks"],
            ],
            [
                True,
                True,
                [
                    "read_taxonomy",
                    "read_data",
                    "search",
                    "todo_write",
                    "switch_mode",
                    "create_form",
                    "create_task",
                    "run_task",
                    "get_task_run",
                    "get_task_run_logs",
                    "list_tasks",
                    "list_task_runs",
                ],
                [],
            ],
        ]
    )
    def test_toolkit_tools_based_on_feature_flags(self, create_form_flag, tasks_flag, expected_tools, unexpected_tools):
        with (
            patch("ee.hogai.chat_agent.mode_manager.has_create_form_tool_feature_flag", return_value=create_form_flag),
            patch("ee.hogai.chat_agent.mode_manager.has_phai_tasks_feature_flag", return_value=tasks_flag),
        ):
            context_manager = AssistantContextManager(
                team=self.team, user=self.user, config=RunnableConfig(configurable={})
            )
            toolkit = ChatAgentToolkit(team=self.team, user=self.user, context_manager=context_manager)
            tool_names = [tool.model_fields["name"].default for tool in toolkit.tools]

            for expected in expected_tools:
                self.assertIn(expected, tool_names)
            for unexpected in unexpected_tools:
                self.assertNotIn(unexpected, tool_names)


class TestAgentNode(ClickhouseTestMixin, BaseTest):
    async def test_node_does_not_get_contextual_tool_if_not_configured(self):
        with (
            patch(
                "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
                return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Simple response")]),
            ),
            patch("ee.hogai.utils.tests.FakeChatOpenAI.bind_tools", return_value=MagicMock()) as mock_bind_tools,
            patch(
                "ee.hogai.tools.replay.filter_session_recordings.FilterSessionRecordingsTool._arun_impl",
                return_value=("Success", {}),
            ),
        ):
            node = _create_agent_node(self.team, self.user)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            next_state = await node.arun(state, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 3)
            # Mode context message
            self.assertIsInstance(next_state.messages[0], ContextMessage)
            assert isinstance(next_state.messages[0], ContextMessage)
            self.assertIn("product_analytics", next_state.messages[0].content)
            # Original human message
            self.assertIsInstance(next_state.messages[1], HumanMessage)
            assert isinstance(next_state.messages[1], HumanMessage)
            self.assertEqual(next_state.messages[1].content, "show me long recordings")
            # Assistant message
            self.assertIsInstance(next_state.messages[2], AssistantMessage)
            assert isinstance(next_state.messages[2], AssistantMessage)
            self.assertEqual(next_state.messages[2].content, "Simple response")
            self.assertEqual(next_state.messages[2].tool_calls, [])
            mock_bind_tools.assert_not_called()

    async def test_node_injects_contextual_tool_prompts(self):
        with patch(
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatAnthropic(
                responses=[LangchainAIMessage(content=[{"text": "I'll help with recordings", "type": "text"}])]
            ),
        ) as mock_get_model:
            node = _create_agent_node(self.team, self.user)
            state = AssistantState(
                messages=[HumanMessage(content="show me long recordings", id="test-id")], start_id="test-id"
            )

            # Test with contextual tools
            config = RunnableConfig(
                configurable={
                    "contextual_tools": {
                        "filter_session_recordings": {"current_filters": {"duration": ">"}, "current_session_id": None}
                    }
                }
            )
            # Set config before calling arun
            node = _create_agent_node(self.team, self.user, config=config)
            result = await node.arun(state, config)
            # Verify the node ran successfully and returned a message
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 4)
            # Mode context message
            self.assertIsInstance(result.messages[0], ContextMessage)
            # Contextual tools context message
            self.assertIsInstance(result.messages[1], ContextMessage)
            assert isinstance(result.messages[1], ContextMessage)
            self.assertIn("filter_session_recordings", result.messages[1].content)
            # Original human message
            self.assertIsInstance(result.messages[2], HumanMessage)
            # The message should be an AssistantMessage
            self.assertIsInstance(result.messages[3], AssistantMessage)
            assert isinstance(result.messages[3], AssistantMessage)
            self.assertEqual(result.messages[3].content, "I'll help with recordings")

            # Verify _get_model was called with a SearchSessionRecordingsTool instance in the tools arg
            mock_get_model.assert_called()
            tools_arg = mock_get_model.call_args[0][1]
            self.assertTrue(
                any(isinstance(tool, FilterSessionRecordingsTool) for tool in tools_arg),
                "SearchSessionRecordingsTool instance not found in tools arg",
            )

    async def test_node_includes_project_org_user_context_in_prompt_template(self):
        with (
            patch("os.environ", {"ANTHROPIC_API_KEY": "foo"}),
            patch("langchain_anthropic.chat_models.ChatAnthropic._agenerate") as mock_generate,
        ):
            mock_generate.return_value = ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Test response"))],
                llm_output={},
            )

            # Set config before calling arun
            config = RunnableConfig(configurable={})
            node = _create_agent_node(self.team, self.user, config=config)

            await node.arun(AssistantState(messages=[HumanMessage(content="Foo?")]), config)

            # Verify _generate was called
            mock_generate.assert_called_once()

            # Get the messages passed to _generate
            call_args = mock_generate.call_args
            messages = call_args[0][0]  # First argument is messages

            # Check that the system messages contain the project/org/user context
            system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
            content_parts = []
            for msg in system_messages:
                if isinstance(msg.content, str):
                    content_parts.append(msg.content)
                else:
                    content_parts.append(str(msg.content))
            system_content = "\n\n".join(content_parts)

            self.assertIn("You are currently in project ", system_content)
            self.assertIn("The user's name appears to be ", system_content)

    async def test_node_includes_core_memory_in_system_prompt(self):
        """Test that core memory content is appended to the conversation in system prompts"""
        with (
            patch("os.environ", {"ANTHROPIC_API_KEY": "foo"}),
            patch("langchain_anthropic.chat_models.ChatAnthropic._agenerate") as mock_generate,
            patch("ee.hogai.core.mixins.AssistantContextMixin._aget_core_memory_text") as mock_core_memory,
        ):
            mock_core_memory.return_value = "User prefers concise responses and technical details"
            mock_generate.return_value = ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Response"))],
                llm_output={},
            )

            config = RunnableConfig(configurable={})
            node = _create_agent_node(self.team, self.user, config=config)

            await node.arun(AssistantState(messages=[HumanMessage(content="Test")]), config)

            # Verify _agenerate was called
            mock_generate.assert_called_once()

            # Get the messages passed to _agenerate
            call_args = mock_generate.call_args
            messages = call_args[0][0]

            # Check system messages contain core memory
            system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]
            self.assertGreater(len(system_messages), 0)

            content_parts = []
            for msg in system_messages:
                if isinstance(msg.content, str):
                    content_parts.append(msg.content)
                else:
                    content_parts.append(str(msg.content))
            system_content = "\n\n".join(content_parts)

            self.assertIn("User prefers concise responses and technical details", system_content)

    @parameterized.expand(
        [
            # (membership_level, add_context, expected_prompt)
            [OrganizationMembership.Level.ADMIN, True, ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT],
            [OrganizationMembership.Level.ADMIN, False, ROOT_BILLING_CONTEXT_ERROR_PROMPT],
            [OrganizationMembership.Level.OWNER, True, ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT],
            [OrganizationMembership.Level.OWNER, False, ROOT_BILLING_CONTEXT_ERROR_PROMPT],
            [OrganizationMembership.Level.MEMBER, True, ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT],
            [OrganizationMembership.Level.MEMBER, False, ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT],
        ]
    )
    async def test_billing_prompts(self, membership_level, add_context, expected_prompt):
        # Set membership level
        membership = await self.user.organization_memberships.aget(organization=self.team.organization)
        membership.level = membership_level
        await membership.asave()

        # Configure billing context if needed
        if add_context:
            billing_context = MaxBillingContext(
                subscription_level=MaxBillingContextSubscriptionLevel.PAID,
                has_active_subscription=True,
                products=[],
                settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
                trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
            )
            config = RunnableConfig(configurable={"billing_context": billing_context.model_dump()})
        else:
            config = RunnableConfig(configurable={})

        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        prompt_builder = ChatAgentPromptBuilder(team=self.team, user=self.user, context_manager=context_manager)
        self.assertEqual(await prompt_builder._get_billing_prompt(), expected_prompt)


class TestRootNodeTools(BaseTest):
    async def test_run_valid_contextual_tool_call(self):
        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="search_session_recordings",
                            args={"change": "Add duration > 5min filter"},
                        )
                    ],
                )
            ],
            root_tool_call_id="xyz",
        )

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = LangchainToolMessage(
            content="✅ Updated session recordings filters.",
            tool_call_id="xyz",
            name="search_session_recordings",
            artifact={"filters": {"duration": {"operator": ">", "value": 300}}},
        )

        with mock_contextual_tool(mock_tool):
            result = await node.arun(
                state,
                {
                    "configurable": {
                        "team": self.team,
                        "user": self.user,
                        "contextual_tools": {"search_session_recordings": {"current_filters": {}}},
                    }
                },
            )

            self.assertIsInstance(result, PartialAssistantState)
            assert result is not None
            self.assertEqual(len(result.messages), 1)
            self.assertIsInstance(result.messages[0], AssistantToolCallMessage)

    async def test_arun_tool_returns_wrong_type_returns_error_message(self):
        """Test that tool returning wrong type returns an error message"""
        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool",
                    id="test-id",
                    tool_calls=[AssistantToolCall(id="tool-123", name="test_tool", args={})],
                )
            ],
            root_tool_call_id="tool-123",
        )

        mock_tool = AsyncMock()
        mock_tool.ainvoke.return_value = "Wrong type"  # Should be LangchainToolMessage

        with mock_contextual_tool(mock_tool):
            result = await node.arun(state, {"configurable": {"contextual_tools": {"test_tool": {}}}})

            self.assertIsInstance(result, PartialAssistantState)
            assert result is not None
            self.assertEqual(len(result.messages), 1)
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].tool_call_id, "tool-123")
            self.assertIn("This tool does not exist.", result.messages[0].content)

    async def test_arun_unknown_tool_returns_error_message(self):
        """Test that unknown tool name returns an error message"""
        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using unknown tool",
                    id="test-id",
                    tool_calls=[AssistantToolCall(id="tool-123", name="unknown_tool", args={})],
                )
            ],
            root_tool_call_id="tool-123",
        )

        with patch("ee.hogai.registry.get_contextual_tool_class", return_value=None):
            result = await node.arun(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            assert result is not None
            self.assertEqual(len(result.messages), 1)
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].tool_call_id, "tool-123")
            self.assertIn("does not exist", result.messages[0].content)
