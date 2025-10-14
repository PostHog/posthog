from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from ee.hogai.graph.root.compaction_manager import AnthropicConversationCompactionManager
from ee.hogai.utils.types.base import AssistantMessageUnion


class TestAnthropicConversationCompactionManager(BaseTest):
    def setUp(self):
        super().setUp()
        self.window_manager = AnthropicConversationCompactionManager()

    def test_find_window_boundary_basic(self):
        """Test finding window boundary with basic messages"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First message", id="1"),
            AssistantMessage(content="Response 1", id="2"),
            HumanMessage(content="Second message", id="3"),
            AssistantMessage(content="Response 2", id="4"),
        ]

        # With high limits, should return the first message
        result = self.window_manager.find_window_boundary(messages, max_messages=10, max_tokens=10000)
        self.assertEqual(result, "1")

    def test_find_window_boundary_message_limit(self):
        """Test window boundary respects message count limit"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Message 1", id="1"),
            AssistantMessage(content="Response 1", id="2"),
            HumanMessage(content="Message 2", id="3"),
            AssistantMessage(content="Response 2", id="4"),
            HumanMessage(content="Message 3", id="5"),
        ]

        # Limit to 2 messages from the end
        result = self.window_manager.find_window_boundary(messages, max_messages=2, max_tokens=10000)
        # Should be at message 4 or 5
        self.assertIn(result, ["4", "5"])

    def test_find_window_boundary_token_limit(self):
        """Test window boundary respects token limit"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Short", id="1"),
            AssistantMessage(content="A" * 1000, id="2"),  # ~250 tokens
            HumanMessage(content="Message", id="3"),
        ]

        # Set token limit that forces early stop
        # Works backwards: processes message 3 (~2 tokens), then message 2 (~250 tokens) which breaks the limit
        result = self.window_manager.find_window_boundary(messages, max_messages=10, max_tokens=100)
        self.assertEqual(result, "2")

    def test_find_window_boundary_stops_at_human_or_assistant(self):
        """Test window boundary ensures it starts at human or assistant message"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First", id="1"),
            AssistantMessage(content="Response", id="2", tool_calls=[AssistantToolCall(id="t1", name="test", args={})]),
            AssistantToolCallMessage(content="Tool result", id="3", tool_call_id="t1"),
            HumanMessage(content="Next", id="4"),
        ]

        result = self.window_manager.find_window_boundary(messages, max_messages=2, max_tokens=10000)
        # Should stop at human or assistant message, not tool call message
        self.assertIn(result, ["2", "4"])

    def test_get_messages_in_window_no_boundary(self):
        """Test getting messages when no boundary is set returns all messages"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First", id="1"),
            AssistantMessage(content="Second", id="2"),
            HumanMessage(content="Third", id="3"),
        ]

        result = self.window_manager.get_messages_in_window(messages, window_start_id=None)
        self.assertEqual(result, messages)

    def test_get_messages_in_window_with_boundary(self):
        """Test getting messages from a specific boundary"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First", id="1"),
            AssistantMessage(content="Second", id="2"),
            HumanMessage(content="Third", id="3"),
            AssistantMessage(content="Fourth", id="4"),
        ]

        result = self.window_manager.get_messages_in_window(messages, window_start_id="2")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].id, "2")
        self.assertEqual(result[-1].id, "4")

    def test_get_messages_in_window_boundary_not_found(self):
        """Test getting messages when boundary ID doesn't exist returns all messages"""
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="First", id="1"),
            AssistantMessage(content="Second", id="2"),
        ]

        result = self.window_manager.get_messages_in_window(messages, window_start_id="99")
        self.assertEqual(result, messages)

    @parameterized.expand(
        [
            # (num_human_messages, token_count, should_compact)
            [1, 70000, False],  # Only 1 human message
            [2, 70000, False],  # Only 2 human messages
            [3, 50000, False],  # 3 human messages but under token limit
            [3, 70000, True],  # 3 human messages and over token limit
            [5, 70000, True],  # Many messages over limit
        ]
    )
    async def test_should_compact_conversation(self, num_human_messages, token_count, should_compact):
        """Test conversation compaction decision based on message count and tokens"""
        # Create messages with the specified number of human messages
        messages: list[BaseMessage] = []
        for i in range(num_human_messages):
            messages.append(LangchainHumanMessage(content=f"Human message {i}"))
            if i < num_human_messages - 1:  # Don't add assistant message after last human
                messages.append(LangchainAIMessage(content=f"Assistant message {i}"))

        # Mock the model and token counting
        mock_model = MagicMock()
        with patch.object(self.window_manager, "_get_token_count", new_callable=AsyncMock, return_value=token_count):
            result = await self.window_manager.should_compact_conversation(mock_model, messages)
            self.assertEqual(result, should_compact)

    def test_get_estimated_tokens_human_message(self):
        """Test token estimation for human messages"""
        message = HumanMessage(content="A" * 100, id="1")  # 100 chars = ~25 tokens
        tokens = self.window_manager._get_estimated_tokens(message)
        self.assertEqual(tokens, 25)

    def test_get_estimated_tokens_assistant_message(self):
        """Test token estimation for assistant messages without tool calls"""
        message = AssistantMessage(content="A" * 100, id="1")  # 100 chars = ~25 tokens
        tokens = self.window_manager._get_estimated_tokens(message)
        self.assertEqual(tokens, 25)

    def test_get_estimated_tokens_assistant_message_with_tool_calls(self):
        """Test token estimation for assistant messages with tool calls"""
        message = AssistantMessage(
            content="A" * 100,  # 100 chars
            id="1",
            tool_calls=[
                AssistantToolCall(
                    id="t1",
                    name="test_tool",
                    args={"key": "value"},  # Small args
                )
            ],
        )
        # Should count content + JSON serialized args
        tokens = self.window_manager._get_estimated_tokens(message)
        # 100 chars content + ~15 chars for args = ~29 tokens
        self.assertGreater(tokens, 25)
        self.assertLess(tokens, 35)

    def test_get_estimated_tokens_tool_call_message(self):
        """Test token estimation for tool call messages"""
        message = AssistantToolCallMessage(content="A" * 200, id="1", tool_call_id="t1")
        tokens = self.window_manager._get_estimated_tokens(message)
        self.assertEqual(tokens, 50)

    async def test_get_token_count_calls_model(self):
        """Test that _get_token_count properly calls the model's token counting"""
        mock_model = MagicMock()
        mock_model.get_num_tokens_from_messages = MagicMock(return_value=1234)

        messages: list[BaseMessage] = [LangchainHumanMessage(content="Test")]
        thinking_config = {"type": "enabled"}

        result = await self.window_manager._get_token_count(mock_model, messages, thinking_config=thinking_config)

        self.assertEqual(result, 1234)
        mock_model.get_num_tokens_from_messages.assert_called_once_with(messages, thinking=thinking_config, tools=None)
