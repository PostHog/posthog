import datetime
from contextlib import contextmanager

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
    ToolMessage as LangchainToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeInterrupt
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

from posthog.models.organization import OrganizationMembership

from products.replay.backend.max_tools import SearchSessionRecordingsTool

from ee.hogai.tool import ToolMessagesArtifact
from ee.hogai.utils.tests import FakeChatAnthropic, FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion

from ..nodes import AgentNode, AgentToolkit, AgentToolsNode
from ..prompts import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
)


@contextmanager
def mock_contextual_tool(mock_tool):
    """Helper to mock a contextual tool class with create_tool_class"""
    mock_tool_class = MagicMock()
    mock_tool_class.create_tool_class = AsyncMock(return_value=mock_tool)

    with patch("ee.hogai.tool.get_contextual_tool_class", return_value=mock_tool_class):
        yield


class TestRootNode(ClickhouseTestMixin, BaseTest):
    async def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")]
            ),
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = await node.arun(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            assistant_message = next_state.messages[0]
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Why did the chicken cross the road? To get to the other side!")

    @parameterized.expand(
        [
            ["trends", "Hang tight while I check this."],
            ["funnel", "Hang tight while I check this."],
            ["retention", "Hang tight while I check this."],
            ["trends", ""],
            ["funnel", ""],
            ["retention", ""],
        ]
    )
    async def test_node_handles_insight_tool_call(self, insight_type, content):
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content=content,
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "create_and_query_insight",
                                "args": {"query_description": "Foobar", "query_kind": insight_type},
                            }
                        ],
                    )
                ],
            ),
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = await node.arun(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            assistant_message = next_state.messages[0]
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, content)
            self.assertIsNotNone(assistant_message.id)
            self.assertIsNotNone(assistant_message.tool_calls)
            assert assistant_message.tool_calls is not None
            self.assertEqual(len(assistant_message.tool_calls), 1)
            self.assertEqual(
                assistant_message.tool_calls[0],
                AssistantToolCall(
                    id="xyz",
                    name="create_and_query_insight",
                    args={"query_description": "Foobar", "query_kind": insight_type},
                ),
            )

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_node_reconstructs_conversation(self, mock_model):
        node = AgentNode(self.team, self.user, AgentToolkit)
        state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
        result = node._construct_messages(
            state_1.messages, state_1.root_conversation_start_id, state_1.root_tool_calls_count
        )
        self.assertEqual(
            result,
            [
                LangchainHumanMessage(
                    content=[{"text": "Hello", "type": "text", "cache_control": {"type": "ephemeral"}}]
                )
            ],
        )

        # We want full access to message history in root
        state_2 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Welcome!"),
                HumanMessage(content="Generate trends"),
            ]
        )
        result2 = node._construct_messages(
            state_2.messages, state_2.root_conversation_start_id, state_2.root_tool_calls_count
        )
        self.assertEqual(
            result2,
            [
                LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]),
                LangchainAIMessage(content=[{"text": "Welcome!", "type": "text"}]),
                LangchainHumanMessage(
                    content=[{"text": "Generate trends", "type": "text", "cache_control": {"type": "ephemeral"}}]
                ),
            ],
        )

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatAnthropic(responses=[]))
    async def test_node_reconstructs_conversation_with_tool_calls(self, mock_model):
        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={},
                        )
                    ],
                ),
                AssistantMessage(content="Follow-up"),
                AssistantToolCallMessage(content="Answer", tool_call_id="xyz"),
                HumanMessage(content="Answer"),
            ]
        )
        result = node._construct_messages(state.messages, state.root_conversation_start_id, state.root_tool_calls_count)
        self.assertEqual(
            result,
            [
                LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]),
                LangchainAIMessage(
                    content=[{"text": "Welcome!", "type": "text"}],
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "create_and_query_insight",
                            "args": {},
                        }
                    ],
                ),
                LangchainHumanMessage(content=[{"type": "tool_result", "tool_use_id": "xyz", "content": "Answer"}]),
                LangchainAIMessage(content=[{"text": "Follow-up", "type": "text"}]),
                LangchainHumanMessage(
                    content=[{"text": "Answer", "type": "text", "cache_control": {"type": "ephemeral"}}]
                ),
            ],
        )

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_node_filters_tool_calls_without_responses(self, mock_model):
        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(
                    content="Welcome!",
                    tool_calls=[
                        # This tool call has a response
                        AssistantToolCall(
                            id="xyz1",
                            name="create_and_query_insight",
                            args={},
                        ),
                        # This tool call has no response and should be filtered out
                        AssistantToolCall(
                            id="xyz2",
                            name="create_and_query_insight",
                            args={},
                        ),
                    ],
                ),
                AssistantToolCallMessage(content="Answer for xyz1", tool_call_id="xyz1"),
            ]
        )
        messages = node._construct_messages(
            state.messages, state.root_conversation_start_id, state.root_tool_calls_count
        )

        # Verify we get exactly 3 messages
        self.assertEqual(len(messages), 3)

        # Verify the messages are in correct order and format
        self.assertEqual(messages[0], LangchainHumanMessage(content=[{"text": "Hello", "type": "text"}]))

        # Verify the assistant message only includes the tool call that has a response
        assistant_message = messages[1]
        self.assertIsInstance(assistant_message, LangchainAIMessage)
        assert isinstance(assistant_message, LangchainAIMessage)
        self.assertEqual(assistant_message.content, [{"text": "Welcome!", "type": "text"}])
        self.assertEqual(len(assistant_message.tool_calls), 1)
        self.assertEqual(assistant_message.tool_calls[0]["id"], "xyz1")

        # Verify the tool response is included
        tool_message = messages[2]
        self.assertIsInstance(tool_message, LangchainHumanMessage)
        assert isinstance(tool_message, LangchainHumanMessage)
        self.assertEqual(
            tool_message.content,
            [
                {
                    "content": "Answer for xyz1",
                    "type": "tool_result",
                    "tool_use_id": "xyz1",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        )

    async def test_hard_limit_removes_tools(self):
        mock_with_tokens = MagicMock()
        ainvoke_mock = AsyncMock()
        ainvoke_mock.return_value = LangchainAIMessage(
            content=[{"text": "I can't help with that anymore.", "type": "text"}], id="1"
        )
        mock_with_tokens.ainvoke = ainvoke_mock

        with patch(
            "ee.hogai.graph.agent_modes.nodes.MaxChatAnthropic",
            return_value=mock_with_tokens,
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)

            # Create a state that has hit the hard limit (4 tool calls)
            state = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=node.MAX_TOOL_CALLS)

            # Run the node
            next_state = await node.arun(state, {})

            # Verify the response doesn't contain any tool calls
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            message = next_state.messages[0]
            self.assertIsInstance(message, AssistantMessage)
            assert isinstance(message, AssistantMessage)
            self.assertEqual(message.content, "I can't help with that anymore.")
            self.assertEqual(message.tool_calls, [])

            # Verify the hard limit message was added to the conversation
            messages = node._construct_messages(
                state.messages, state.root_conversation_start_id, state.root_tool_calls_count
            )
            self.assertIn("iterations", messages[-1].content)

    async def test_node_gets_contextual_tool(self):
        with patch("ee.hogai.graph.agent_modes.nodes.MaxChatAnthropic") as mock_chat_openai:
            mock_model = MagicMock()
            mock_model.get_num_tokens_from_messages.return_value = 100
            mock_model.bind_tools.return_value = mock_model
            mock_chat_openai.return_value = mock_model

            node = AgentNode(self.team, self.user, AgentToolkit)
            # Set the config on the node so context_manager can access it
            config = RunnableConfig(
                configurable={"contextual_tools": {"search_session_recordings": {"current_filters": {"duration": ">"}}}}
            )
            node._config = config
            # Clear any cached context manager to force recreation with new config
            node._context_manager = None

            # Mock get_contextual_tool_class to return a real tool-like class
            with (
                patch.object(node, "_has_session_summarization_feature_flag", return_value=False),
            ):
                # Create a mock tool instance
                mock_tool_instance = MagicMock()
                mock_tool_instance.name = "search_session_recordings"

                # Create a mock tool class with async create_tool_class
                mock_tool_class = MagicMock()
                mock_tool_class.create_tool_class = AsyncMock(return_value=mock_tool_instance)

                # We need to patch at the point where it's imported
                with patch("ee.hogai.tool.get_contextual_tool_class") as mock_get_tool:
                    mock_get_tool.return_value = mock_tool_class

                    # Verify that context_manager has the right tools
                    context_tools = node.context_manager.get_contextual_tools()
                    self.assertEqual(
                        context_tools, {"search_session_recordings": {"current_filters": {"duration": ">"}}}
                    )

                    tools = await node._get_tools(
                        AssistantState(messages=[HumanMessage(content="show me long recordings")]), config
                    )

                    node._get_model(
                        AssistantState(messages=[HumanMessage(content="show me long recordings")]),
                        tools,
                    )

                    # Verify get_contextual_tool_class was called
                    mock_get_tool.assert_called_once_with("search_session_recordings")

                    # Verify bind_tools was called
                    mock_model.bind_tools.assert_called_once()
                    tools = mock_model.bind_tools.call_args[0][0]

                    # Verify that our mock tool instance is in the list
                    self.assertIn(mock_tool_instance, tools)

    async def test_node_does_not_get_contextual_tool_if_not_configured(self):
        with (
            patch(
                "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
                return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Simple response")]),
            ),
            patch("ee.hogai.utils.tests.FakeChatOpenAI.bind_tools", return_value=MagicMock()) as mock_bind_tools,
            patch(
                "products.replay.backend.max_tools.SearchSessionRecordingsTool._arun_impl",
                return_value=("Success", {}),
            ),
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)
            state = AssistantState(messages=[HumanMessage(content="show me long recordings")])

            next_state = await node.arun(state, {})

            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Simple response")
            self.assertEqual(assistant_message.tool_calls, [])
            mock_bind_tools.assert_not_called()

    async def test_node_injects_contextual_tool_prompts(self):
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatAnthropic(
                responses=[LangchainAIMessage(content=[{"text": "I'll help with recordings", "type": "text"}])]
            ),
        ) as mock_get_model:
            node = AgentNode(self.team, self.user, AgentToolkit)
            state = AssistantState(
                messages=[HumanMessage(content="show me long recordings", id="test-id")], start_id="test-id"
            )

            # Test with contextual tools
            config = RunnableConfig(
                configurable={"contextual_tools": {"search_session_recordings": {"current_filters": {"duration": ">"}}}}
            )
            # Set config before calling arun
            node._config = config
            result = await node.arun(state, config)

            # Verify the node ran successfully and returned a message
            self.assertIsInstance(result, PartialAssistantState)
            self.assertEqual(len(result.messages), 3)
            # Context message
            self.assertIsInstance(result.messages[0], ContextMessage)
            assert isinstance(result.messages[0], ContextMessage)
            self.assertIn("search_session_recordings", result.messages[0].content)
            # Original human message
            self.assertIsInstance(result.messages[1], HumanMessage)
            # The message should be an AssistantMessage, not VisualizationMessage
            self.assertIsInstance(result.messages[2], AssistantMessage)
            assert isinstance(result.messages[2], AssistantMessage)
            self.assertEqual(result.messages[2].content, "I'll help with recordings")

            # Verify _get_model was called with a SearchSessionRecordingsTool instance in the tools arg
            mock_get_model.assert_called()
            tools_arg = mock_get_model.call_args[0][1]
            self.assertTrue(
                any(isinstance(tool, SearchSessionRecordingsTool) for tool in tools_arg),
                "SearchSessionRecordingsTool instance not found in tools arg",
            )

    async def test_node_includes_project_org_user_context_in_prompt_template(self):
        with (
            patch("os.environ", {"ANTHROPIC_API_KEY": "foo"}),
            patch("langchain_anthropic.chat_models.ChatAnthropic._agenerate") as mock_generate,
            # patch("ee.hogai.graph.agent_modes.nodes.AgentNode._find_new_window_id", return_value=None),
        ):
            mock_generate.return_value = ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Test response"))],
                llm_output={},
            )

            node = AgentNode(self.team, self.user, AgentToolkit)
            # Set config before calling arun
            config = RunnableConfig(configurable={})
            node._config = config

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

        node = AgentNode(self.team, self.user, AgentToolkit)

        # Configure billing context if needed
        if add_context:
            billing_context = MaxBillingContext(
                subscription_level=MaxBillingContextSubscriptionLevel.PAID,
                has_active_subscription=True,
                products=[],
                settings=MaxBillingContextSettings(autocapture_on=True, active_destinations=0),
                trial=MaxBillingContextTrial(is_active=True, expires_at=str(datetime.date(2023, 2, 1)), target="scale"),
            )
            node._config = RunnableConfig(configurable={"billing_context": billing_context.model_dump()})
        else:
            node._config = RunnableConfig(configurable={})

        self.assertEqual(await node._get_billing_prompt(node._config), expected_prompt)

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    @patch(
        "ee.hogai.graph.agent_modes.compaction_manager.AnthropicConversationCompactionManager.should_compact_conversation"
    )
    @patch("ee.hogai.graph.conversation_summarizer.nodes.AnthropicConversationSummarizer.summarize")
    async def test_conversation_summarization_flow(self, mock_summarize, mock_should_compact, mock_model):
        """Test that conversation is summarized when it gets too long"""
        mock_should_compact.return_value = True
        mock_summarize.return_value = "This is a summary of the conversation so far."

        mock_model_instance = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response after summary")])
        mock_model.return_value = mock_model_instance

        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="First response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ]
        )
        result = await node.arun(state, {})

        # Verify summarize was called with all messages
        mock_summarize.assert_called_once()
        summarized_messages = mock_summarize.call_args[0][0]
        self.assertEqual(len(summarized_messages), 3)

        # Verify summary message was inserted
        self.assertIsInstance(result, PartialAssistantState)
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        self.assertEqual(len(context_messages), 1)
        self.assertIn("This is a summary of the conversation so far.", context_messages[0].content)

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    @patch(
        "ee.hogai.graph.agent_modes.compaction_manager.AnthropicConversationCompactionManager.should_compact_conversation"
    )
    @patch("ee.hogai.graph.conversation_summarizer.nodes.AnthropicConversationSummarizer.summarize")
    async def test_conversation_summarization_on_first_turn(self, mock_summarize, mock_should_compact, mock_model):
        """Test that on first turn, the last message is excluded from summarization"""
        mock_should_compact.return_value = True
        mock_summarize.return_value = "Summary without last message"

        mock_model_instance = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])
        mock_model.return_value = mock_model_instance

        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="First response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ],
            start_id="3",  # Mark the last message as the start (first turn)
        )
        await node.arun(state, {})

        # Verify last message was excluded from summarization
        mock_summarize.assert_called_once()
        summarized_messages = mock_summarize.call_args[0][0]
        self.assertEqual(len(summarized_messages), 2)

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model")
    @patch("posthoganalytics.feature_enabled")
    async def test_get_tools_session_summarization_feature_flag(self, mock_feature_enabled, mock_model):
        """Test that session_summarization tool is only included when feature flag is enabled"""
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])

        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(messages=[HumanMessage(content="Test")])

        # Test with feature flag enabled
        mock_feature_enabled.return_value = True
        tools_with_flag = await node._get_tools(state, {})
        tool_names_with_flag = [tool.name if hasattr(tool, "name") else tool.__name__ for tool in tools_with_flag]
        self.assertIn("session_summarization", tool_names_with_flag)

        # Test with feature flag disabled
        mock_feature_enabled.return_value = False
        tools_without_flag = await node._get_tools(state, {})
        tool_names_without_flag = [tool.name if hasattr(tool, "name") else tool.__name__ for tool in tools_without_flag]
        self.assertNotIn("session_summarization", tool_names_without_flag)

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model")
    @patch("ee.hogai.tool.get_contextual_tool_class")
    async def test_get_tools_ignores_unknown_contextual_tools(self, mock_get_tool_class, mock_model):
        """Test that unknown contextual tools (None from get_contextual_tool_class) are ignored"""
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])
        mock_get_tool_class.return_value = None  # Simulates unknown tool

        node = AgentNode(self.team, self.user, AgentToolkit)
        state = AssistantState(messages=[HumanMessage(content="Test")])
        config = RunnableConfig(configurable={"contextual_tools": {"unknown_tool": {"some": "config"}}})

        # Should not raise an error, just skip the unknown tool
        tools = await node._get_tools(state, config)
        self.assertIsNotNone(tools)

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_construct_messages_empty_list(self, mock_model):
        """Test _construct_messages with empty message list"""
        node = AgentNode(self.team, self.user, AgentToolkit)
        result = node._construct_messages([], None, None)
        self.assertEqual(result, [])

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_construct_messages_cache_control_only_on_last_eligible_message(self, mock_model):
        """Test that cache_control is only added to the last eligible message"""
        node = AgentNode(self.team, self.user, AgentToolkit)
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First", id="1"),
            AssistantMessage(content="Response", id="2"),
            HumanMessage(content="Second", id="3"),
        ]
        result = node._construct_messages(messages, None, None)

        # Count how many messages have cache_control
        cache_control_count = 0
        for msg in result:
            if isinstance(msg.content, list):
                for content_item in msg.content:
                    if isinstance(content_item, dict) and "cache_control" in content_item:
                        cache_control_count += 1

        self.assertEqual(cache_control_count, 1, "Only one message should have cache_control")

    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model", return_value=FakeChatOpenAI(responses=[]))
    async def test_construct_messages_with_hard_limit_reached(self, mock_model):
        """Test that hard limit prompt is added when tool calls reach MAX_TOOL_CALLS"""
        node = AgentNode(self.team, self.user, AgentToolkit)
        messages = [HumanMessage(content="Test", id="1")]
        result = node._construct_messages(messages, None, node.MAX_TOOL_CALLS)

        # Verify hard limit message is added
        human_messages = [msg for msg in result if isinstance(msg, LangchainHumanMessage)]
        self.assertGreater(len(human_messages), 1)
        self.assertIn("iterations", human_messages[-1].content)

    @parameterized.expand(
        [
            [23, False],  # MAX_TOOL_CALLS - 1
            [24, True],  # MAX_TOOL_CALLS
            [25, True],  # MAX_TOOL_CALLS + 1
            [None, False],
        ]
    )
    def test_is_hard_limit_reached_boundary_conditions(self, tool_calls_count, expected):
        """Test _is_hard_limit_reached with boundary values"""
        node = AgentNode(self.team, self.user, AgentToolkit)
        result = node._is_hard_limit_reached(tool_calls_count)
        self.assertEqual(result, expected)

    async def test_node_increments_tool_count_on_tool_call(self):
        """Test that RootNode increments tool count when assistant makes a tool call"""
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content="Let me help",
                        tool_calls=[
                            {
                                "id": "tool-1",
                                "name": "create_and_query_insight",
                                "args": {"query_description": "test"},
                            }
                        ],
                    )
                ]
            ),
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)

            # Test starting from no tool calls
            state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
            result_1 = await node.arun(state_1, {})
            self.assertEqual(result_1.root_tool_calls_count, 1)

            # Test incrementing from existing count
            state_2 = AssistantState(
                messages=[HumanMessage(content="Hello")],
                root_tool_calls_count=5,
            )
            result_2 = await node.arun(state_2, {})
            self.assertEqual(result_2.root_tool_calls_count, 6)

    async def test_node_resets_tool_count_on_plain_response(self):
        """Test that RootNode resets tool count when assistant responds without tool calls"""
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Here's your answer")]),
        ):
            node = AgentNode(self.team, self.user, AgentToolkit)

            state = AssistantState(
                messages=[HumanMessage(content="Hello")],
                root_tool_calls_count=5,
            )
            result = await node.arun(state, {})
            self.assertIsNone(result.root_tool_calls_count)

    def test_router_returns_end_for_plain_response(self):
        """Test that router returns END when message has no tool calls"""
        from ee.hogai.utils.types import AssistantNodeName

        node = AgentNode(self.team, self.user, AgentToolkit)

        state = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Hi there!"),
            ]
        )
        result = node.router(state)
        self.assertEqual(result, AssistantNodeName.END)

    def test_router_returns_send_for_single_tool_call(self):
        """Test that router returns Send for single tool call"""
        from langgraph.types import Send

        from ee.hogai.utils.types import AssistantNodeName

        node = AgentNode(self.team, self.user, AgentToolkit)

        state = AssistantState(
            messages=[
                HumanMessage(content="Generate insights"),
                AssistantMessage(
                    content="Let me help",
                    tool_calls=[
                        AssistantToolCall(
                            id="tool-1",
                            name="create_and_query_insight",
                            args={"query_description": "test"},
                        )
                    ],
                ),
            ]
        )
        result = node.router(state)

        # Verify it's a list of Send objects
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Send)
        self.assertEqual(result[0].node, AssistantNodeName.ROOT_TOOLS)
        self.assertEqual(result[0].arg.root_tool_call_id, "tool-1")

    def test_router_returns_multiple_sends_for_parallel_tool_calls(self):
        """Test that router returns multiple Send objects for parallel tool calls"""
        from langgraph.types import Send

        from ee.hogai.utils.types import AssistantNodeName

        node = AgentNode(self.team, self.user, AgentToolkit)

        state = AssistantState(
            messages=[
                HumanMessage(content="Generate multiple insights"),
                AssistantMessage(
                    content="Let me create several insights",
                    tool_calls=[
                        AssistantToolCall(
                            id="tool-1",
                            name="create_and_query_insight",
                            args={"query_description": "trends"},
                        ),
                        AssistantToolCall(
                            id="tool-2",
                            name="create_and_query_insight",
                            args={"query_description": "funnel"},
                        ),
                        AssistantToolCall(
                            id="tool-3",
                            name="create_and_query_insight",
                            args={"query_description": "retention"},
                        ),
                    ],
                ),
            ]
        )
        result = node.router(state)

        # Verify it's a list of Send objects
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 3)

        # Verify all are Send objects to ROOT_TOOLS
        for i, send in enumerate(result):
            self.assertIsInstance(send, Send)
            self.assertEqual(send.node, AssistantNodeName.ROOT_TOOLS)
            self.assertEqual(send.arg.root_tool_call_id, f"tool-{i+1}")


class TestRootNodeTools(BaseTest):
    def test_node_tools_router(self):
        node = AgentToolsNode(self.team, self.user, AgentToolkit)

        # Test case 1: Last message is AssistantToolCallMessage - should return "root"
        state_1 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(node.router(state_1), "root")

        # Test case 2: No tool call message or root tool call - should return "end"
        state_3 = AssistantState(messages=[AssistantMessage(content="Hello")])
        self.assertEqual(node.router(state_3), "end")

        # Test case 3: Has contextual tool call result - should go back to root
        state_4 = AssistantState(
            messages=[
                AssistantMessage(content="Hello"),
                AssistantToolCallMessage(content="Tool result", tool_call_id="xyz"),
            ]
        )
        self.assertEqual(node.router(state_4), "root")

    async def test_run_no_assistant_message(self):
        node = AgentToolsNode(self.team, self.user, AgentToolkit)
        state = AssistantState(messages=[HumanMessage(content="Hello")])
        result = await node.arun(state, {})
        self.assertEqual(result, PartialAssistantState(root_tool_call_id=None))

    @patch("ee.hogai.tools.create_and_query_insight.CreateAndQueryInsightTool._arun_impl")
    async def test_run_valid_tool_call(self, create_and_query_insight_mock):
        test_message = AssistantToolCallMessage(content="Tool result", tool_call_id="xyz", id="msg-1")
        create_and_query_insight_mock.return_value = ("", ToolMessagesArtifact(messages=[test_message]))

        node = AgentToolsNode(self.team, self.user, AgentToolkit)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="create_and_query_insight",
                            args={"query_description": "test query"},
                        )
                    ],
                )
            ],
            root_tool_call_id="xyz",
        )
        result = await node.arun(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "xyz")
        create_and_query_insight_mock.assert_called_once_with(query_description="test query")

    async def test_run_valid_contextual_tool_call(self):
        node = AgentToolsNode(self.team, self.user, AgentToolkit)
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

    async def test_navigate_tool_call_raises_node_interrupt(self):
        """Test that navigate tool calls raise NodeInterrupt to pause graph execution"""
        node = AgentToolsNode(self.team, self.user, AgentToolkit)

        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="I'll help you navigate to insights",
                    id="test-id",
                    tool_calls=[AssistantToolCall(id="nav-123", name="navigate", args={"page_key": "insights"})],
                )
            ],
            root_tool_call_id="nav-123",
        )

        mock_navigate_tool = AsyncMock()
        mock_navigate_tool.ainvoke.return_value = LangchainToolMessage(
            content="XXX", tool_call_id="nav-123", artifact={"page_key": "insights"}
        )

        with mock_contextual_tool(mock_navigate_tool):
            # The navigate tool call should raise NodeInterrupt
            with self.assertRaises(NodeInterrupt) as cm:
                await node.arun(state, {"configurable": {"contextual_tools": {"navigate": {}}}})

            # Verify the NodeInterrupt contains the expected message
            # NodeInterrupt wraps the message in an Interrupt object
            interrupt_data = cm.exception.args[0]
            if isinstance(interrupt_data, list):
                interrupt_data = interrupt_data[0].value
            self.assertIsInstance(interrupt_data, AssistantToolCallMessage)
            self.assertEqual(interrupt_data.content, "XXX")
            self.assertEqual(interrupt_data.tool_call_id, "nav-123")
            self.assertEqual(interrupt_data.ui_payload, {"navigate": {"page_key": "insights"}})

    async def test_arun_tool_returns_wrong_type_returns_error_message(self):
        """Test that tool returning wrong type returns an error message"""
        node = AgentToolsNode(self.team, self.user, AgentToolkit)
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
            self.assertIn("internal error", result.messages[0].content)

    async def test_arun_unknown_tool_returns_error_message(self):
        """Test that unknown tool name returns an error message"""
        node = AgentToolsNode(self.team, self.user, AgentToolkit)
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

        with patch("ee.hogai.tool.get_contextual_tool_class", return_value=None):
            result = await node.arun(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            assert result is not None
            self.assertEqual(len(result.messages), 1)
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].tool_call_id, "tool-123")
            self.assertIn("does not exist", result.messages[0].content)
