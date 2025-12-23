from contextlib import contextmanager

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    HumanMessage,
)

from posthog.models import Team, User

from ee.hogai.chat_agent.mode_manager import ChatAgentModeManager
from ee.hogai.context import AssistantContextManager
from ee.hogai.tool_errors import MaxToolError, MaxToolFatalError, MaxToolRetryableError, MaxToolTransientError
from ee.hogai.tools.read_taxonomy import ReadEvents
from ee.hogai.utils.tests import FakeChatAnthropic, FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantNodeName, NodePath


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

    # Use the mode manager's node property which calls configure()
    return mode_manager.node


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

    # Use the mode manager's tools_node property which calls configure()
    return mode_manager.tools_node


class TestAgentNode(ClickhouseTestMixin, BaseTest):
    async def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatOpenAI(
                responses=[LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")]
            ),
        ):
            node = _create_agent_node(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = await node.arun(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            # The state includes context messages + original message + generated message
            self.assertGreaterEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[-1]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Why did the chicken cross the road? To get to the other side!")

    async def test_node_can_produce_not_existing_tool(self):
        """Test that the node can produce a not existing tool call message. AgentToolsExecutable will handle the hallucination."""
        with patch(
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content="Content",
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "does_not_exist",
                                "args": {"query_description": "Foobar"},
                            }
                        ],
                    )
                ],
            ),
        ):
            node = _create_agent_node(self.team, self.user)
            state_1 = AssistantState(messages=[HumanMessage(content="generate")])
            next_state = await node.arun(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            # The state includes context messages + original message + generated message
            self.assertGreaterEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[-1]
            self.assertIsInstance(assistant_message, AssistantMessage)
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Content")
            self.assertIsNotNone(assistant_message.id)
            self.assertIsNotNone(assistant_message.tool_calls)
            assert assistant_message.tool_calls is not None
            self.assertEqual(len(assistant_message.tool_calls), 1)
            self.assertEqual(
                assistant_message.tool_calls[0],
                AssistantToolCall(
                    id="xyz",
                    name="does_not_exist",
                    args={"query_description": "Foobar"},
                ),
            )

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    async def test_node_reconstructs_conversation(self, mock_model):
        node = _create_agent_node(self.team, self.user)
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

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
        return_value=FakeChatAnthropic(responses=[]),
    )
    async def test_node_reconstructs_conversation_with_tool_calls(self, mock_model):
        node = _create_agent_node(self.team, self.user)
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

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    async def test_node_filters_tool_calls_without_responses(self, mock_model):
        node = _create_agent_node(self.team, self.user)
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

        with (
            patch(
                "ee.hogai.core.agent_modes.executables.MaxChatAnthropic",
                return_value=mock_with_tokens,
            ),
            patch(
                "ee.hogai.core.agent_modes.compaction_manager.AnthropicConversationCompactionManager.calculate_token_count",
                return_value=1000,
            ),
        ):
            node = _create_agent_node(self.team, self.user)

            # Create a state that has hit the hard limit (4 tool calls)
            state = AssistantState(messages=[HumanMessage(content="Hello")], root_tool_calls_count=node.MAX_TOOL_CALLS)

            # Run the node
            next_state = await node.arun(state, {})

            # Verify the response doesn't contain any tool calls
            self.assertIsInstance(next_state, PartialAssistantState)
            # The state includes context messages + original message + generated message
            self.assertGreaterEqual(len(next_state.messages), 1)
            message = next_state.messages[-1]
            self.assertIsInstance(message, AssistantMessage)
            assert isinstance(message, AssistantMessage)
            self.assertEqual(message.content, "I can't help with that anymore.")
            self.assertEqual(message.tool_calls, [])

            # Verify the hard limit message was added to the conversation
            messages = node._construct_messages(
                state.messages, state.root_conversation_start_id, state.root_tool_calls_count
            )
            self.assertIn("iterations", messages[-1].content)

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    @patch("ee.hogai.core.agent_modes.compaction_manager.AnthropicConversationCompactionManager.calculate_token_count")
    @patch("ee.hogai.utils.conversation_summarizer.AnthropicConversationSummarizer.summarize")
    async def test_conversation_summarization_flow(self, mock_summarize, mock_calculate_tokens, mock_model):
        """Test that conversation is summarized when it gets too long"""
        # Return a token count higher than CONVERSATION_WINDOW_SIZE (100,000)
        mock_calculate_tokens.return_value = 150_000
        mock_summarize.return_value = "This is a summary of the conversation so far."

        mock_model_instance = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response after summary")])
        mock_model.return_value = mock_model_instance

        node = _create_agent_node(self.team, self.user)
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

        # Verify summary message was inserted (along with mode reminder)
        self.assertIsInstance(result, PartialAssistantState)
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        self.assertEqual(len(context_messages), 2)  # summary + mode reminder
        summary_msg = next(msg for msg in context_messages if "This is a summary" in msg.content)
        self.assertIn("This is a summary of the conversation so far.", summary_msg.content)

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    @patch("ee.hogai.core.agent_modes.compaction_manager.AnthropicConversationCompactionManager.calculate_token_count")
    @patch("ee.hogai.utils.conversation_summarizer.AnthropicConversationSummarizer.summarize")
    async def test_conversation_summarization_on_first_turn(self, mock_summarize, mock_calculate_tokens, mock_model):
        """Test that on first turn, the last message is excluded from summarization"""
        # Return a token count higher than CONVERSATION_WINDOW_SIZE (100,000)
        mock_calculate_tokens.return_value = 150_000
        mock_summarize.return_value = "Summary without last message"

        mock_model_instance = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])
        mock_model.return_value = mock_model_instance

        node = _create_agent_node(self.team, self.user)
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

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    @patch("ee.hogai.core.agent_modes.compaction_manager.AnthropicConversationCompactionManager.calculate_token_count")
    @patch("ee.hogai.utils.conversation_summarizer.AnthropicConversationSummarizer.summarize")
    async def test_conversation_summarization_includes_mode_reminder_when_feature_flag_enabled(
        self, mock_summarize, mock_calculate_tokens, mock_model
    ):
        """Test that mode reminder is inserted after summary when modes feature flag is enabled"""
        mock_calculate_tokens.return_value = 150_000
        mock_summarize.return_value = "Summary of conversation"

        mock_model_instance = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])
        mock_model.return_value = mock_model_instance

        node = _create_agent_node(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="First response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ],
            agent_mode=AgentMode.PRODUCT_ANALYTICS,
        )

        result = await node.arun(state, {})

        # Verify summary and mode reminder messages were inserted
        self.assertIsInstance(result, PartialAssistantState)
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        self.assertGreaterEqual(len(context_messages), 2, "Should have at least summary and mode reminder")

        # Find summary message
        summary_msg = next(
            (msg for msg in context_messages if "Summary of conversation" in msg.content),
            None,
        )
        self.assertIsNotNone(summary_msg, "Summary message should be present")
        assert summary_msg is not None  # Type narrowing

        # Find mode reminder message
        mode_reminder = next(
            (msg for msg in context_messages if "product_analytics" in msg.content),
            None,
        )
        self.assertIsNotNone(mode_reminder, "Mode reminder should be present")
        assert mode_reminder is not None  # Type narrowing

        # Verify mode reminder comes after summary
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_msg.id)
        mode_idx = next(i for i, msg in enumerate(result.messages) if msg.id == mode_reminder.id)
        self.assertEqual(mode_idx, summary_idx + 1, "Mode reminder should be right after summary")

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    async def test_construct_messages_empty_list(self, mock_model):
        """Test _construct_messages with empty message list"""
        node = _create_agent_node(self.team, self.user)
        result = node._construct_messages([], None, None)
        self.assertEqual(result, [])

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    async def test_construct_messages_cache_control_only_on_last_eligible_message(self, mock_model):
        """Test that cache_control is only added to the last eligible message"""
        node = _create_agent_node(self.team, self.user)
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

    @patch(
        "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model", return_value=FakeChatOpenAI(responses=[])
    )
    async def test_construct_messages_with_hard_limit_reached(self, mock_model):
        """Test that hard limit prompt is added when tool calls reach MAX_TOOL_CALLS"""
        node = _create_agent_node(self.team, self.user)
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
        node = _create_agent_node(self.team, self.user)
        result = node._is_hard_limit_reached(tool_calls_count)
        self.assertEqual(result, expected)

    async def test_node_increments_tool_count_on_tool_call(self):
        """Test that RootNode increments tool count when assistant makes a tool call"""
        with patch(
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
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
            node = _create_agent_node(self.team, self.user)

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
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Here's your answer")]),
        ):
            node = _create_agent_node(self.team, self.user)

            state = AssistantState(
                messages=[HumanMessage(content="Hello")],
                root_tool_calls_count=5,
            )
            result = await node.arun(state, {})
            self.assertIsNone(result.root_tool_calls_count)

    def test_router_returns_end_for_plain_response(self):
        """Test that router returns END when message has no tool calls"""
        from ee.hogai.utils.types import AssistantNodeName

        node = _create_agent_node(self.team, self.user)

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

        node = _create_agent_node(self.team, self.user)

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

        node = _create_agent_node(self.team, self.user)

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

    def test_get_updated_agent_mode(self):
        node = _create_agent_node(self.team, self.user)
        message = AssistantMessage(content="test")
        self.assertEqual(
            node._get_updated_agent_mode(message, AgentMode.PRODUCT_ANALYTICS), AgentMode.PRODUCT_ANALYTICS
        )

    @patch("ee.hogai.core.agent_modes.executables.AgentExecutable._get_model")
    @patch("ee.hogai.core.agent_modes.compaction_manager.AnthropicConversationCompactionManager.calculate_token_count")
    @patch("ee.hogai.utils.conversation_summarizer.AnthropicConversationSummarizer.summarize")
    async def test_node_returns_replace_messages_that_replaces_and_reorders(
        self, mock_summarize, mock_calculate_tokens, mock_model
    ):
        """Test that the node returns ReplaceMessages that replaces and reorders existing messages."""
        from langgraph.graph import END, START, StateGraph

        from ee.hogai.utils.types.base import ReplaceMessages

        # Trigger summarization flow which returns ReplaceMessages
        mock_calculate_tokens.return_value = 150_000
        mock_summarize.return_value = "Conversation summary"
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])

        node = _create_agent_node(self.team, self.user)
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Second message", id="2"),
                HumanMessage(content="Third message", id="3"),
            ]
        )

        result = await node.arun(state, {})

        # Verify the node returns ReplaceMessages
        self.assertIsInstance(result.messages, ReplaceMessages)

        # Build a graph to verify the ReplaceMessages behavior
        graph = StateGraph(AssistantState)
        graph.add_node("node", lambda _: result)
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()

        res = await compiled_graph.ainvoke(
            {
                "messages": [
                    # Different order/content than what the node returns
                    HumanMessage(content="Original A", id="A"),
                    AssistantMessage(content="Original B", id="B"),
                ]
            }
        )

        # Verify the original messages were replaced entirely (not merged)
        # The result should contain only messages from the node's ReplaceMessages
        message_ids = [msg.id for msg in res["messages"]]
        self.assertNotIn("A", message_ids)
        self.assertNotIn("B", message_ids)

        # Verify the new messages are present with the summary context inserted
        context_messages = [msg for msg in res["messages"] if isinstance(msg, ContextMessage)]
        self.assertGreaterEqual(len(context_messages), 1)
        self.assertTrue(any("summary" in msg.content.lower() for msg in context_messages))


class TestRootNodeTools(BaseTest):
    def test_node_tools_router(self):
        node = _create_agent_tools_node(self.team, self.user)

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
        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(messages=[HumanMessage(content="Hello")])
        result = await node.arun(state, {})
        self.assertEqual(result, PartialAssistantState(root_tool_call_id=None))

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_run_valid_tool_call(self, read_taxonomy_mock):
        """Test that built-in tools can be called"""
        read_taxonomy_mock.return_value = ("Content", None)

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="read_taxonomy",
                            args={"query": {"kind": "events"}},
                        )
                    ],
                )
            ],
            root_tool_call_id="xyz",
        )
        result = await node(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "xyz")
        read_taxonomy_mock.assert_called_once_with(query=ReadEvents())

    async def test_invalid_tool_call_returns_error(self):
        """Test that invalid tool calls return an error message"""
        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Hello",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(
                            id="xyz",
                            name="does_not_exist",
                            args={"query_description": "Foobar"},
                        )
                    ],
                )
            ],
            root_tool_call_id="xyz",
        )
        result = await node(state, {})
        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "xyz")
        self.assertIn("This tool does not exist", result.messages[0].content)

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_max_tool_fatal_error_returns_error_message(self, read_taxonomy_mock):
        """Test that MaxToolFatalError is caught and converted to tool message."""
        read_taxonomy_mock.side_effect = MaxToolFatalError(
            "Configuration error: INKEEP_API_KEY environment variable is not set"
        )

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool that will fail",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        result = await node.arun(state, {})

        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "tool-123")
        self.assertIn("Configuration error", result.messages[0].content)
        self.assertIn("INKEEP_API_KEY", result.messages[0].content)
        self.assertNotIn("retry", result.messages[0].content.lower())

    @patch("ee.hogai.core.agent_modes.executables.posthoganalytics.capture")
    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_max_tool_fatal_error_emits_analytics_event(self, read_taxonomy_mock, capture_mock):
        """Test that MaxToolFatalError emits a PostHog analytics event."""
        error_message = "Configuration error: INKEEP_API_KEY environment variable is not set"
        read_taxonomy_mock.side_effect = MaxToolFatalError(error_message)

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool that will fail",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        # Provide a config with distinct_id so the capture is triggered
        config = RunnableConfig(configurable={"distinct_id": "test-user-123"})
        await node.arun(state, config)

        # Verify posthoganalytics.capture was called
        capture_mock.assert_called_once()
        call_args = capture_mock.call_args

        # Verify event name
        self.assertEqual(call_args.kwargs["event"], "max_tool_error")

        # Verify distinct_id is set
        self.assertEqual(call_args.kwargs["distinct_id"], "test-user-123")

        # Verify properties
        properties = call_args.kwargs["properties"]
        self.assertEqual(properties["tool_name"], "read_taxonomy")
        self.assertEqual(properties["error_type"], "MaxToolFatalError")
        self.assertEqual(properties["retry_strategy"], "never")
        self.assertEqual(properties["error_message"], error_message)

        # Verify groups are set
        groups = call_args.kwargs["groups"]
        self.assertIn("organization", groups)
        self.assertIn("project", groups)

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_max_tool_error_groups_call_works_in_async_context(self, read_taxonomy_mock):
        """Test that groups() call in error handler works in async context without SynchronousOnlyOperation."""
        read_taxonomy_mock.side_effect = MaxToolFatalError("Test error")

        # Re-fetch the user from DB to simulate production behavior where
        # current_organization is NOT pre-loaded (it's lazy-loaded)
        fresh_user = await User.objects.aget(id=self.user.id)

        node = _create_agent_tools_node(self.team, fresh_user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool that will fail",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        # This config triggers the posthoganalytics.capture path
        config = RunnableConfig(configurable={"distinct_id": "test-user-123"})

        # This must not raise SynchronousOnlyOperation in the groups() call
        result = await node.arun(state, config)

        # Should complete without error
        self.assertIsInstance(result, PartialAssistantState)

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_max_tool_retryable_error_returns_error_with_retry_hint(self, read_taxonomy_mock):
        """Test that MaxToolRetryableError includes retry hint for adjusted inputs."""
        read_taxonomy_mock.side_effect = MaxToolRetryableError(
            "Invalid entity kind: 'unknown_entity'. Must be one of: person, session, organization"
        )

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool with invalid input",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        result = await node.arun(state, {})

        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "tool-123")
        self.assertIn("Invalid entity kind", result.messages[0].content)
        self.assertIn("retry with adjusted inputs", result.messages[0].content.lower())

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_max_tool_transient_error_returns_error_with_once_retry_hint(self, read_taxonomy_mock):
        """Test that MaxToolTransientError includes hint to retry once without changes."""
        read_taxonomy_mock.side_effect = MaxToolTransientError("Rate limit exceeded. Please try again in a few moments")

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool that hits rate limit",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        result = await node.arun(state, {})

        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "tool-123")
        self.assertIn("Rate limit exceeded", result.messages[0].content)
        self.assertIn("retry this operation once without changes", result.messages[0].content.lower())

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_generic_exception_returns_internal_error_message(self, read_taxonomy_mock):
        """Test that generic exceptions are caught and return internal error message."""
        read_taxonomy_mock.side_effect = RuntimeError("Unexpected internal error")

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool that crashes unexpectedly",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        result = await node.arun(state, {})

        self.assertIsInstance(result, PartialAssistantState)
        assert result is not None
        self.assertEqual(len(result.messages), 1)
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        self.assertEqual(result.messages[0].tool_call_id, "tool-123")
        self.assertIn("internal error", result.messages[0].content.lower())
        self.assertIn("do not immediately retry", result.messages[0].content.lower())

    @parameterized.expand(
        [
            ("fatal", MaxToolFatalError("Fatal error"), "never"),
            ("transient", MaxToolTransientError("Transient error"), "once"),
            ("retryable", MaxToolRetryableError("Retryable error"), "adjusted"),
        ]
    )
    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_all_error_types_are_logged_with_retry_strategy(
        self, name, error, expected_strategy, read_taxonomy_mock
    ):
        """Test that all MaxToolError types are logged with their retry strategy."""
        read_taxonomy_mock.side_effect = error

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        with patch("ee.hogai.core.agent_modes.executables.capture_exception") as mock_capture:
            _ = await node.arun(state, {})

            mock_capture.assert_called_once()
            call_kwargs = mock_capture.call_args.kwargs
            captured_error = mock_capture.call_args.args[0]

            self.assertIsInstance(captured_error, MaxToolError)
            self.assertEqual(call_kwargs["properties"]["retry_strategy"], expected_strategy)
            self.assertEqual(call_kwargs["properties"]["tool"], "read_taxonomy")

    @patch("ee.hogai.tools.read_taxonomy.ReadTaxonomyTool._run_impl")
    async def test_validation_error_returns_error_message(self, read_taxonomy_mock):
        """Test that pydantic ValidationError is caught and converted to tool message."""
        from pydantic import ValidationError as PydanticValidationError

        read_taxonomy_mock.side_effect = PydanticValidationError.from_exception_data(
            "ValidationError",
            [
                {
                    "type": "missing",
                    "loc": ("query", "kind"),
                    "input": {},
                }
            ],
        )

        node = _create_agent_tools_node(self.team, self.user)
        state = AssistantState(
            messages=[
                AssistantMessage(
                    content="Using tool with invalid args",
                    id="test-id",
                    tool_calls=[
                        AssistantToolCall(id="tool-123", name="read_taxonomy", args={"query": {"kind": "events"}})
                    ],
                )
            ],
            root_tool_call_id="tool-123",
        )

        with patch("ee.hogai.core.agent_modes.executables.capture_exception") as mock_capture:
            result = await node.arun(state, {})

            self.assertIsInstance(result, PartialAssistantState)
            assert result is not None
            self.assertEqual(len(result.messages), 1)
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            self.assertEqual(result.messages[0].tool_call_id, "tool-123")
            self.assertIn("validation error", result.messages[0].content.lower())
            self.assertIn("field required", result.messages[0].content.lower())

            # Verify exception was captured
            mock_capture.assert_called_once()
            captured_error = mock_capture.call_args.args[0]
            from pydantic import ValidationError as PydanticValidationError

            self.assertIsInstance(captured_error, PydanticValidationError)
