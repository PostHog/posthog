from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, ContextMessage, HumanMessage

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
        self.assertEqual(result, "3")

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

    def test_update_window_with_large_last_tool_call_message(self):
        """
        Test that update_window handles a large (128k) final AssistantToolCallMessage.
        When the last messages are too large to fit into the window, the start human message
        should be copied to the start of the window along with the summary message.
        """
        # Create a very large tool call message (128k characters)
        large_content = "x" * (128 * 1024)
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Initial question", id=start_id),
            AssistantMessage(
                content="Let me analyze that",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-1",
                        name="create_and_query_insight",
                        args={"query_description": "test"},
                    )
                ],
            ),
            AssistantToolCallMessage(
                content=large_content,
                tool_call_id="tool-1",
            ),
        ]

        summary_message = ContextMessage(content="Summary of previous conversation", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # When the window boundary is None (messages too large), we expect:
        # - Original messages preserved
        # - Summary message appended
        # - Start message copied
        # - Window start should be the summary message
        self.assertEqual(len(result.messages), 5)
        self.assertEqual(result.messages[0].id, start_id)
        self.assertEqual(result.messages[-2].id, summary_id)
        last_msg = result.messages[-1]
        assert isinstance(last_msg, HumanMessage)  # Type narrowing
        self.assertEqual(last_msg.content, "Initial question")
        self.assertNotEqual(last_msg.id, start_id)
        self.assertEqual(result.updated_start_id, last_msg.id)
        self.assertEqual(result.updated_window_start_id, summary_id)

    def test_update_window_initiator_in_window(self):
        """
        Test update_window when the initiator (start) human message is within the new window boundary.
        In this case, the summary should be inserted before the start message,
        and the window start should be updated to the found boundary.
        """
        start_id = str(uuid4())
        summary_id = str(uuid4())

        # Create a conversation where the start message will be in the window
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Old question 1", id=str(uuid4())),
            AssistantMessage(content="Old response 1"),
            HumanMessage(content="Old question 2", id=str(uuid4())),
            AssistantMessage(content="Old response 2"),
            HumanMessage(content="Recent question", id=start_id),
            AssistantMessage(content="Recent response"),
        ]

        summary_message = ContextMessage(content="Summary of conversation", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # The start message is in the window, so summary should be inserted before it
        # Find where the summary was inserted
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        start_idx = next(i for i, msg in enumerate(result.messages) if msg.id == start_id)

        # Summary should come before start message
        self.assertLess(summary_idx, start_idx)
        # Start ID should remain the same
        self.assertEqual(result.updated_start_id, start_id)
        # Window start should be set to a boundary candidate
        self.assertIsNotNone(result.updated_window_start_id)

    def test_update_window_initiator_not_in_window(self):
        """
        Test update_window when the initiator (start) human message is NOT in the new window boundary.
        In this case, a copy of the start message should be inserted at the window start,
        along with the summary message.
        """
        start_id = str(uuid4())
        summary_id = str(uuid4())

        # Create many messages to push the start message outside the window
        # The window boundary is determined by max_messages=16 and max_tokens=2048
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Initial question", id=start_id),
            AssistantMessage(content="Initial response"),
        ]

        # Add enough messages to push start_id out of the window
        for i in range(20):
            messages.append(HumanMessage(content=f"Question {i}", id=str(uuid4())))
            messages.append(AssistantMessage(content=f"Response {i}" * 50))  # Make messages larger

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # The start message should NOT be in the result (only its copy)
        start_messages = [msg for msg in result.messages if msg.id == start_id]
        self.assertEqual(len(start_messages), 0, "Original start message should not be in result")

        # Find the copied start message (same content, different ID)
        copied_start = next(
            (msg for msg in result.messages if isinstance(msg, HumanMessage) and msg.content == "Initial question"),
            None,
        )
        self.assertIsNotNone(copied_start, "Copied start message should exist")
        assert copied_start is not None  # Type narrowing
        self.assertNotEqual(copied_start.id, start_id, "Copied message should have new ID")

        # The copied start message should have a new ID returned
        self.assertEqual(result.updated_start_id, copied_start.id)

        # Summary and copied start should be at the beginning of the window
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        self.assertEqual(result.messages[summary_idx + 1].id, copied_start.id, "Copied start should follow summary")

    def test_tool_call_complete_sequence_in_window(self):
        """
        Test that complete tool call sequences within the window boundary are preserved.
        When both AssistantMessage with tool_calls and AssistantToolCallMessage are in
        the window, they should both be preserved.
        """
        start_id = str(uuid4())
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Old message", id=str(uuid4())),
            AssistantMessage(content="Old response"),
            HumanMessage(content="Recent question", id=start_id),
            AssistantMessage(
                content="Let me check",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-1",
                        name="create_and_query_insight",
                        args={"query": "test"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="Tool result", tool_call_id="tool-1"),
            AssistantMessage(content="Final response"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # Count tool calls in output
        tool_call_count = 0
        tool_result_count = 0
        for msg in result.messages:
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                tool_call_count += len(msg.tool_calls)
            elif isinstance(msg, AssistantToolCallMessage):
                tool_result_count += 1

        # All tool calls and results should be preserved
        self.assertEqual(tool_call_count, tool_result_count, "Tool calls and results should match in output")
        self.assertGreater(tool_call_count, 0, "Should preserve at least some tool calls")

    def test_tool_call_incomplete_at_window_boundary(self):
        """
        Test that incomplete tool call sequences at the window boundary are handled correctly.
        When tool call sequences are split by the window boundary, the system should maintain
        consistency (either preserve both parts or remove both).
        """
        start_id = str(uuid4())
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question 1", id=str(uuid4())),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-old",
                        name="create_and_query_insight",
                        args={"query": "old"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="Result", tool_call_id="tool-old"),
            # Add many messages to push above out of window
            HumanMessage(content="Q2", id=str(uuid4())),
            AssistantMessage(content="R2" * 100),
            HumanMessage(content="Q3", id=str(uuid4())),
            AssistantMessage(content="R3" * 100),
            HumanMessage(content="Q4", id=str(uuid4())),
            AssistantMessage(content="R4" * 100),
            HumanMessage(content="Q5", id=str(uuid4())),
            AssistantMessage(content="R5" * 100),
            HumanMessage(content="Q6", id=start_id),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-new",
                        name="create_and_query_insight",
                        args={"query": "new"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="New result", tool_call_id="tool-new"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # Count tool calls in output
        tool_call_count = 0
        tool_result_count = 0
        for msg in result.messages:
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                tool_call_count += len(msg.tool_calls)
            elif isinstance(msg, AssistantToolCallMessage):
                tool_result_count += 1

        # Even when removing incomplete sequences, remaining should be complete
        self.assertEqual(
            tool_call_count,
            tool_result_count,
            "Even when removing incomplete sequences, remaining should be complete",
        )

    def test_tool_call_multiple_complete_sequences(self):
        """
        Test that multiple complete tool call sequences are all preserved.
        When there are multiple consecutive tool calls, all complete sequences
        should be maintained in the output.
        """
        start_id = str(uuid4())
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-1",
                        name="create_and_query_insight",
                        args={"query": "first"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="First result", tool_call_id="tool-1"),
            AssistantMessage(
                content="",
                tool_calls=[
                    AssistantToolCall(
                        id="tool-2",
                        name="create_and_query_insight",
                        args={"query": "second"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="Second result", tool_call_id="tool-2"),
            AssistantMessage(content="Done"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # Count tool calls in output
        tool_call_count = 0
        tool_result_count = 0
        for msg in result.messages:
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                tool_call_count += len(msg.tool_calls)
            elif isinstance(msg, AssistantToolCallMessage):
                tool_result_count += 1

        # All complete sequences should be preserved
        self.assertEqual(tool_call_count, tool_result_count, "Tool calls and results should match in output")
        self.assertEqual(tool_call_count, 2, "Should preserve both tool calls")

    def test_update_window_with_empty_messages(self):
        """Test that update_window handles edge case of empty messages list"""
        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        # This should raise ValueError because there's no start message
        with self.assertRaises(ValueError) as context:
            self.window_manager.update_window([], summary_message, start_id="nonexistent")

        self.assertIn("Start message not found", str(context.exception))

    def test_update_window_with_nonexistent_start_id(self):
        """
        Test that update_window handles a nonexistent start_id.
        When start_id doesn't exist, find_start_message falls back to the first HumanMessage.
        """
        actual_id = str(uuid4())
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=actual_id),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        # When start_id doesn't exist, it falls back to the first human message
        result = self.window_manager.update_window(messages, summary_message, start_id="nonexistent-id")

        # The first human message should be used as the start message
        self.assertIsNotNone(result)
        # The actual_id message should be found and used
        found_actual_id = any(msg.id == actual_id for msg in result.messages)
        self.assertTrue(found_actual_id, "Should fall back to first human message when start_id not found")

    def test_update_window_preserves_message_ids(self):
        """Test that all messages in the result have valid IDs"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(content="Response", id=str(uuid4())),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # Verify all messages have IDs
        for msg in result.messages:
            self.assertIsNotNone(msg.id, f"Message should have an ID: {msg}")
            self.assertIsInstance(msg.id, str, f"Message ID should be a string: {msg.id}")

    def test_update_window_with_no_window_boundary(self):
        """Test update_window when messages are too large to fit in window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        # Create messages with large content that will exceed the window
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(content="x" * 10000),  # Large message
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # When there's no window boundary, the summary and copied start message are appended
        self.assertEqual(len(result.messages), 4)  # original 2 + summary + copied start
        self.assertEqual(result.messages[-2].id, summary_id)
        self.assertEqual(result.updated_window_start_id, summary_id)
        # Updated start ID should be the copied message
        self.assertNotEqual(result.updated_start_id, start_id)

    def test_update_window_single_message_conversation(self):
        """Test update_window with a minimal single-message conversation"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(messages, summary_message, start_id=start_id)

        # Should insert summary before the start message
        self.assertGreater(len(result.messages), 1)
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        self.assertIsNotNone(summary_idx)
