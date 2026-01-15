from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
)
from parameterized import parameterized

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantTool,
    AssistantToolCall,
    AssistantToolCallMessage,
    ContextMessage,
    HumanMessage,
)

from ee.hogai.utils.types.base import AssistantMessageUnion

from ..compaction_manager import AnthropicConversationCompactionManager


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
            [1, 90000, False],  # Only 1 human message, under limit
            [2, 90000, False],  # Only 2 human messages, under limit
            [3, 80000, False],  # 3 human messages but under token limit
            [3, 110000, True],  # 3 human messages and over token limit
            [5, 110000, True],  # Many messages over limit
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

    async def test_should_compact_conversation_with_tools_under_limit(self):
        """Test that tools are accounted for when estimating tokens with 2 or fewer human messages"""
        from langchain_core.tools import tool

        @tool
        def test_tool(query: str) -> str:
            """A test tool"""
            return f"Result for {query}"

        messages: list[BaseMessage] = [
            LangchainHumanMessage(content="A" * 1000),  # ~250 tokens
            LangchainAIMessage(content="B" * 1000),  # ~250 tokens
        ]
        tools = [test_tool]

        mock_model = MagicMock()
        # With 2 human messages, should use estimation and not call _get_token_count
        result = await self.window_manager.should_compact_conversation(mock_model, messages, tools=tools)

        # Total should be well under 100k limit
        self.assertFalse(result)

    async def test_should_compact_conversation_with_tools_over_limit(self):
        """Test that tools push estimation over limit with 2 or fewer human messages"""
        messages: list[BaseMessage] = [
            LangchainHumanMessage(content="A" * 200000),  # ~50k tokens
            LangchainAIMessage(content="B" * 200000),  # ~50k tokens
        ]

        # Create large tool schemas to push over 100k limit
        tools = [{"type": "function", "function": {"name": f"tool_{i}", "description": "X" * 1000}} for i in range(100)]

        mock_model = MagicMock()
        result = await self.window_manager.should_compact_conversation(mock_model, messages, tools=tools)

        # Should be over the 100k limit
        self.assertTrue(result)

    def test_get_estimated_assistant_message_tokens_human_message(self):
        """Test token estimation for human messages"""
        message = HumanMessage(content="A" * 100, id="1")  # 100 chars = ~25 tokens
        tokens = self.window_manager._get_estimated_assistant_message_tokens(message)
        self.assertEqual(tokens, 25)

    def test_get_estimated_assistant_message_tokens_assistant_message(self):
        """Test token estimation for assistant messages without tool calls"""
        message = AssistantMessage(content="A" * 100, id="1")  # 100 chars = ~25 tokens
        tokens = self.window_manager._get_estimated_assistant_message_tokens(message)
        self.assertEqual(tokens, 25)

    def test_get_estimated_assistant_message_tokens_assistant_message_with_tool_calls(self):
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
        tokens = self.window_manager._get_estimated_assistant_message_tokens(message)
        # 100 chars content + ~15 chars for args = ~29 tokens
        self.assertGreater(tokens, 25)
        self.assertLess(tokens, 35)

    def test_get_estimated_assistant_message_tokens_tool_call_message(self):
        """Test token estimation for tool call messages"""
        message = AssistantToolCallMessage(content="A" * 200, id="1", tool_call_id="t1")
        tokens = self.window_manager._get_estimated_assistant_message_tokens(message)
        self.assertEqual(tokens, 50)

    def test_get_estimated_langchain_message_tokens_string_content(self):
        """Test token estimation for langchain messages with string content"""
        message = LangchainHumanMessage(content="A" * 100)
        tokens = self.window_manager._get_estimated_langchain_message_tokens(message)
        self.assertEqual(tokens, 25)

    def test_get_estimated_langchain_message_tokens_list_content_with_strings(self):
        """Test token estimation for langchain messages with list of string content"""
        message = LangchainHumanMessage(content=["A" * 100, "B" * 100])
        tokens = self.window_manager._get_estimated_langchain_message_tokens(message)
        self.assertEqual(tokens, 50)

    def test_get_estimated_langchain_message_tokens_list_content_with_dicts(self):
        """Test token estimation for langchain messages with dict content"""
        message = LangchainHumanMessage(content=[{"type": "text", "text": "A" * 100}])
        tokens = self.window_manager._get_estimated_langchain_message_tokens(message)
        # 100 chars for text + overhead for JSON structure
        self.assertGreater(tokens, 25)
        self.assertLess(tokens, 40)

    def test_get_estimated_langchain_message_tokens_ai_message_with_tool_calls(self):
        """Test token estimation for AI messages with tool calls"""
        message = LangchainAIMessage(
            content="A" * 100,
            tool_calls=[
                {"id": "t1", "name": "test_tool", "args": {"key": "value"}},
                {"id": "t2", "name": "another_tool", "args": {"foo": "bar"}},
            ],
        )
        tokens = self.window_manager._get_estimated_langchain_message_tokens(message)
        # Content + tool calls JSON
        self.assertGreater(tokens, 25)
        self.assertLess(tokens, 70)

    def test_get_estimated_langchain_message_tokens_ai_message_without_tool_calls(self):
        """Test token estimation for AI messages without tool calls"""
        message = LangchainAIMessage(content="A" * 100)
        tokens = self.window_manager._get_estimated_langchain_message_tokens(message)
        self.assertEqual(tokens, 25)

    def test_count_json_tokens(self):
        """Test JSON token counting helper"""
        json_data = {"key": "value", "nested": {"foo": "bar"}}
        char_count = self.window_manager._count_json_tokens(json_data)
        # Should match length of compact JSON
        import json

        expected = len(json.dumps(json_data, separators=(",", ":")))
        self.assertEqual(char_count, expected)

    def test_get_estimated_tools_tokens_empty(self):
        """Test tool token estimation with no tools"""
        tokens = self.window_manager._get_estimated_tools_tokens([])
        self.assertEqual(tokens, 0)

    def test_get_estimated_tools_tokens_with_dict_tools(self):
        """Test tool token estimation with dict tools"""
        tools = [
            {"type": "function", "function": {"name": "test_tool", "description": "A test tool"}},
        ]
        tokens = self.window_manager._get_estimated_tools_tokens(tools)
        # Should be positive and reasonable
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, 100)

    def test_get_estimated_tools_tokens_with_base_tool(self):
        """Test tool token estimation with BaseTool"""
        from langchain_core.tools import tool

        @tool
        def sample_tool(query: str) -> str:
            """A sample tool for testing"""
            return f"Result for {query}"

        tools = [sample_tool]
        tokens = self.window_manager._get_estimated_tools_tokens(tools)
        # Should count the tool schema
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, 200)

    def test_get_estimated_tools_tokens_multiple_tools(self):
        """Test tool token estimation with multiple tools"""
        from langchain_core.tools import tool

        @tool
        def tool1(x: int) -> int:
            """First tool"""
            return x * 2

        @tool
        def tool2(y: str) -> str:
            """Second tool"""
            return y.upper()

        tools = [tool1, tool2]
        tokens = self.window_manager._get_estimated_tools_tokens(tools)
        # Should count both tool schemas
        self.assertGreater(tokens, 0)
        self.assertLess(tokens, 400)

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
                        name="create_insight",
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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # When the window boundary is None (messages too large), we expect:
        # - Original messages preserved
        # - Summary message appended
        # - Mode reminder appended
        # - Start message copied
        # - Window start should be the summary message
        self.assertEqual(len(result.messages), 6)
        self.assertEqual(result.messages[0].id, start_id)
        self.assertEqual(result.messages[-3].id, summary_id)
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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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

        # Summary, mode reminder, and copied start should be at the beginning of the window
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        # Mode reminder is injected between summary and copied start
        self.assertEqual(
            result.messages[summary_idx + 2].id, copied_start.id, "Copied start should follow mode reminder"
        )

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
                        name="create_insight",
                        args={"query": "test"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="Tool result", tool_call_id="tool-1"),
            AssistantMessage(content="Final response"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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
                        name="create_insight",
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
                        name="create_insight",
                        args={"query": "new"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="New result", tool_call_id="tool-new"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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
                        name="create_insight",
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
                        name="create_insight",
                        args={"query": "second"},
                    )
                ],
            ),
            AssistantToolCallMessage(content="Second result", tool_call_id="tool-2"),
            AssistantMessage(content="Done"),
        ]

        summary_message = ContextMessage(content="Summary", id=str(uuid4()))

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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
            self.window_manager.update_window([], summary_message, AgentMode.PRODUCT_ANALYTICS, start_id="nonexistent")

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
        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id="nonexistent-id"
        )

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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # When there's no window boundary, the summary, mode reminder, and copied start message are appended
        self.assertEqual(len(result.messages), 5)  # original 2 + summary + mode reminder + copied start
        self.assertEqual(result.messages[-3].id, summary_id)
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

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should insert summary before the start message
        self.assertGreater(len(result.messages), 1)
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        self.assertIsNotNone(summary_idx)

    def test_mode_message_injection_when_feature_flag_enabled_no_boundary(self):
        """Test that mode reminder is injected after summary when feature flag is enabled and no window boundary"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(content="x" * 10000),  # Large message to force no boundary
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.PRODUCT_ANALYTICS,
            start_id=start_id,
        )

        # Verify full message list structure: original messages + summary + mode reminder + copied start
        self.assertEqual(len(result.messages), 5)
        self.assertIsInstance(result.messages[0], HumanMessage)
        self.assertEqual(result.messages[0].id, start_id)
        self.assertIsInstance(result.messages[1], AssistantMessage)
        self.assertIsInstance(result.messages[2], ContextMessage)
        self.assertEqual(result.messages[2].id, summary_id)
        assert isinstance(result.messages[2], ContextMessage)
        self.assertIn("Summary", result.messages[2].content)
        self.assertIsInstance(result.messages[3], ContextMessage)
        assert isinstance(result.messages[3], ContextMessage)
        self.assertIn("product_analytics", result.messages[3].content)
        self.assertNotEqual(result.messages[3].id, summary_id)
        self.assertIsInstance(result.messages[4], HumanMessage)
        self.assertNotEqual(result.messages[4].id, start_id)  # Copied start message has new ID

    def test_mode_message_injection_when_feature_flag_enabled_start_in_window(self):
        """Test that mode reminder is injected after summary when start message is in window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Old question 1", id=str(uuid4())),
            AssistantMessage(content="Old response 1"),
            HumanMessage(content="Recent question", id=start_id),
            AssistantMessage(content="Recent response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.SQL,
            start_id=start_id,
        )

        # Find where summary and mode reminder were inserted
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        mode_idx = next(
            i for i, msg in enumerate(result.messages) if isinstance(msg, ContextMessage) and "sql" in msg.content
        )
        start_idx = next(i for i, msg in enumerate(result.messages) if msg.id == start_id)

        # Verify mode reminder is right after summary, and both are before start message
        self.assertEqual(mode_idx, summary_idx + 1)
        self.assertLess(mode_idx, start_idx)
        summary_msg = result.messages[summary_idx]
        self.assertIsInstance(summary_msg, ContextMessage)
        assert isinstance(summary_msg, ContextMessage)
        self.assertIn("Summary", summary_msg.content)
        mode_msg = result.messages[mode_idx]
        self.assertIsInstance(mode_msg, ContextMessage)
        assert isinstance(mode_msg, ContextMessage)
        self.assertIn("sql", mode_msg.content)

    def test_mode_message_injection_when_feature_flag_enabled_start_outside_window(self):
        """Test that mode reminder is injected after summary when start message is outside window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Initial question", id=start_id),
            AssistantMessage(content="Initial response"),
        ]

        # Add enough messages to push start_id out of the window
        for i in range(20):
            messages.append(HumanMessage(content=f"Question {i}", id=str(uuid4())))
            messages.append(AssistantMessage(content=f"Response {i}" * 50))

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.SESSION_REPLAY,
            start_id=start_id,
        )

        # Verify structure: summary at start, then mode reminder, then copied start, then window messages
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        mode_idx = next(
            i
            for i, msg in enumerate(result.messages)
            if isinstance(msg, ContextMessage) and "session_replay" in msg.content
        )
        copied_start = next(
            (msg for msg in result.messages if isinstance(msg, HumanMessage) and msg.content == "Initial question"),
            None,
        )
        self.assertIsNotNone(copied_start)
        assert copied_start is not None
        copied_start_idx = next(i for i, msg in enumerate(result.messages) if msg.id == copied_start.id)

        # Mode reminder right after summary, copied start right after mode reminder
        self.assertEqual(mode_idx, summary_idx + 1, "Mode reminder should be right after summary")
        self.assertEqual(copied_start_idx, mode_idx + 1, "Copied start should be right after mode reminder")
        summary_msg = result.messages[summary_idx]
        self.assertIsInstance(summary_msg, ContextMessage)
        assert isinstance(summary_msg, ContextMessage)
        self.assertIn("Summary", summary_msg.content)
        mode_msg = result.messages[mode_idx]
        self.assertIsInstance(mode_msg, ContextMessage)
        assert isinstance(mode_msg, ContextMessage)
        self.assertIn("session_replay", mode_msg.content)
        self.assertIsInstance(result.messages[copied_start_idx], HumanMessage)
        self.assertNotEqual(copied_start.id, start_id)

    def test_no_mode_message_injection_when_mode_evident_in_window(self):
        """Test that mode reminder is not injected when mode is already evident from switch_mode tool call"""

        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Switching mode",
                tool_calls=[
                    AssistantToolCall(
                        id="switch-1",
                        name=AssistantTool.SWITCH_MODE,
                        args={"mode": "product_analytics"},
                    )
                ],
            ),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.PRODUCT_ANALYTICS,
            start_id=start_id,
        )

        # Verify only summary context message exists (no mode reminder)
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        self.assertEqual(len(context_messages), 1, "Should only have summary context message")
        summary_ctx_msg = context_messages[0]
        self.assertEqual(summary_ctx_msg.id, summary_id)
        assert isinstance(summary_ctx_msg, ContextMessage)
        self.assertIn("Summary", summary_ctx_msg.content)
        # Verify switch_mode tool call is still present
        switch_mode_msgs = [
            msg
            for msg in result.messages
            if isinstance(msg, AssistantMessage)
            and msg.tool_calls
            and any(tc.name == AssistantTool.SWITCH_MODE for tc in msg.tool_calls)
        ]
        self.assertEqual(len(switch_mode_msgs), 1, "Switch mode tool call should be preserved")

    def test_no_mode_message_injection_when_initial_mode_message_present(self):
        """Test that mode reminder is not injected when initial mode message is already present"""
        from ee.hogai.context.prompts import CONTEXT_INITIAL_MODE_PROMPT

        start_id = str(uuid4())
        summary_id = str(uuid4())
        initial_mode_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            ContextMessage(content=CONTEXT_INITIAL_MODE_PROMPT.format(mode="product_analytics"), id=initial_mode_id),
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.PRODUCT_ANALYTICS,
            start_id=start_id,
        )

        # Should have initial mode message and summary, but no mode reminder
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        self.assertGreaterEqual(len(context_messages), 2, "Should have initial mode message and summary")

        # Verify initial mode message is still present
        initial_mode_present = any(
            msg.id == initial_mode_id and CONTEXT_INITIAL_MODE_PROMPT.format(mode="product_analytics") in msg.content
            for msg in context_messages
        )
        self.assertTrue(initial_mode_present, "Initial mode message should be preserved")

        # Verify summary is present
        summary_present = any(msg.id == summary_id for msg in context_messages)
        self.assertTrue(summary_present, "Summary should be present")

        # Verify no mode reminder was added
        from ee.hogai.core.agent_modes.prompts import ROOT_AGENT_MODE_REMINDER_PROMPT

        mode_reminders = [
            msg
            for msg in result.messages
            if isinstance(msg, ContextMessage)
            and ROOT_AGENT_MODE_REMINDER_PROMPT.format(mode="product_analytics") in msg.content
        ]
        self.assertEqual(len(mode_reminders), 0, "Should not add mode reminder when initial mode message is present")

    def test_mode_message_content_matches_agent_mode(self):
        """Test that mode reminder content matches the agent mode"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        test_modes = [
            AgentMode.PRODUCT_ANALYTICS,
            AgentMode.SQL,
            AgentMode.SESSION_REPLAY,
        ]

        for mode in test_modes:
            messages: list[AssistantMessageUnion] = [
                HumanMessage(content="Question", id=start_id),
                AssistantMessage(content="Response"),
            ]

            summary_message = ContextMessage(content="Summary", id=summary_id)

            result = self.window_manager.update_window(
                messages,
                summary_message,
                mode,
                start_id=start_id,
            )

            # Verify two context messages: summary and mode reminder
            context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
            self.assertEqual(len(context_messages), 2, f"Should have summary and mode reminder for {mode.value}")

            # First should be summary
            self.assertEqual(context_messages[0].id, summary_id)
            assert isinstance(context_messages[0], ContextMessage)
            self.assertIn("Summary", context_messages[0].content)

            # Second should be mode reminder with correct mode
            mode_reminder = context_messages[1]
            self.assertIsNotNone(mode_reminder, f"Mode reminder should be present for {mode.value}")
            assert isinstance(mode_reminder, ContextMessage)
            self.assertIn(mode.value, mode_reminder.content, f"Mode reminder should contain {mode.value}")
            self.assertNotEqual(mode_reminder.id, summary_id, "Mode reminder should have different ID from summary")

    def test_mode_message_injected_when_old_messages_have_mode_indicator_but_new_window_doesnt(self):
        """
        Test edge case: when no window boundary is found and old messages (outside window) contain
        mode indicators (like switch_mode tool call), the mode reminder should still be injected
        in the NEW window because the new window doesn't have the mode indicator.
        """
        start_id = str(uuid4())
        summary_id = str(uuid4())

        # Old messages contain a switch_mode tool call (which will be outside the new window)
        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Switching mode",
                tool_calls=[
                    AssistantToolCall(
                        id="switch-1",
                        name=AssistantTool.SWITCH_MODE,
                        args={"mode": "product_analytics"},
                    )
                ],
            ),
            AssistantMessage(content="x" * 10000),  # Large message to force no boundary
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages,
            summary_message,
            AgentMode.PRODUCT_ANALYTICS,
            start_id=start_id,
        )

        # The result should have: original messages + summary + mode reminder + copied start
        # Even though old messages have switch_mode, the NEW window (summary + copied start) doesn't
        self.assertEqual(len(result.messages), 6)

        # When we filter to get messages in the new window, we should have mode reminder
        window_messages = self.window_manager.get_messages_in_window(
            result.messages, window_start_id=result.updated_window_start_id
        )

        # Window should contain: summary + mode reminder + copied start
        self.assertEqual(len(window_messages), 3)
        self.assertEqual(window_messages[0].id, summary_id)
        self.assertIsInstance(window_messages[1], ContextMessage)
        assert isinstance(window_messages[1], ContextMessage)
        self.assertIn("product_analytics", window_messages[1].content)
        self.assertIsInstance(window_messages[2], HumanMessage)

        # Verify the mode reminder is NOT the switch_mode tool call
        has_switch_mode_in_window = any(
            isinstance(msg, AssistantMessage)
            and msg.tool_calls
            and any(tc.name == AssistantTool.SWITCH_MODE for tc in msg.tool_calls)
            for msg in window_messages
        )
        self.assertFalse(has_switch_mode_in_window, "New window should not contain old switch_mode tool call")

    def test_todo_reminder_not_injected_when_no_todo_in_conversation(self):
        """Test that todo reminder is not injected when no TODO_WRITE tool calls exist"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should only have summary and mode reminder, no todo reminder
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        human_messages = [msg for msg in result.messages if isinstance(msg, HumanMessage)]

        # Should have 2 context messages: summary + mode reminder
        self.assertEqual(len(context_messages), 2)
        # Should only have 1 human message (the original)
        self.assertEqual(len(human_messages), 1)
        self.assertEqual(human_messages[0].id, start_id)

    def test_todo_reminder_not_injected_when_todo_in_window(self):
        """Test that todo reminder is not injected when TODO_WRITE is within the window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())
        todo_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Creating todos",
                id=todo_id,
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={
                            "todos": [
                                {"content": "Task 1", "status": "pending", "id": "1"},
                                {"content": "Task 2", "status": "in_progress", "id": "2"},
                            ]
                        },
                    )
                ],
            ),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have the original todo message, no todo reminder
        todo_messages = [
            msg
            for msg in result.messages
            if isinstance(msg, AssistantMessage)
            and msg.tool_calls
            and any(tc.name == AssistantTool.TODO_WRITE for tc in msg.tool_calls)
        ]
        self.assertEqual(len(todo_messages), 1)
        self.assertEqual(todo_messages[0].id, todo_id)

        # Should not have a HumanMessage with "todo list" in content
        human_messages_with_todo = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(human_messages_with_todo), 0)

    def test_todo_reminder_injected_when_todo_outside_window_no_boundary(self):
        """Test todo reminder injection when no window boundary and todo is outside"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Creating todos",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={
                            "todos": [
                                {"content": "Find events", "status": "pending", "id": "1"},
                                {"content": "Create plan", "status": "in_progress", "id": "2"},
                            ]
                        },
                    )
                ],
            ),
            AssistantMessage(content="x" * 10000),  # Large message to force no boundary
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have a HumanMessage with todo reminder
        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)
        todo_reminder = todo_reminders[0]
        self.assertIn("Find events", todo_reminder.content)
        self.assertIn("Create plan", todo_reminder.content)
        self.assertIn("system_reminder", todo_reminder.content)

        # Verify order: summary → todo reminder → mode reminder → copied start
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        todo_idx = next(i for i, msg in enumerate(result.messages) if msg.id == todo_reminder.id)
        mode_idx = next(
            i
            for i, msg in enumerate(result.messages)
            if isinstance(msg, ContextMessage) and "product_analytics" in msg.content
        )

        self.assertEqual(todo_idx, summary_idx + 1, "Todo reminder should be right after summary")
        self.assertEqual(mode_idx, todo_idx + 1, "Mode reminder should be right after todo reminder")

    def test_todo_reminder_injected_when_todo_outside_window_start_in_window(self):
        """Test todo reminder injection when start is in window but todo is not"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Old question 1", id=str(uuid4())),
            AssistantMessage(
                content="Creating todos",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Analyze data", "status": "pending", "id": "1"}]},
                    )
                ],
            ),
            HumanMessage(content="Old question 2", id=str(uuid4())),
            AssistantMessage(content="Old response 2"),
        ]

        # Add many messages to push todo out of window but keep start in window
        for i in range(10):
            messages.append(HumanMessage(content=f"Question {i}", id=str(uuid4())))
            messages.append(AssistantMessage(content=f"Response {i}"))

        messages.append(HumanMessage(content="Recent question", id=start_id))
        messages.append(AssistantMessage(content="Recent response"))

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have a HumanMessage with todo reminder
        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)
        self.assertIn("Analyze data", todo_reminders[0].content)

        # Verify order
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        todo_idx = next(i for i, msg in enumerate(result.messages) if msg.id == todo_reminders[0].id)
        start_idx = next(i for i, msg in enumerate(result.messages) if msg.id == start_id)

        self.assertLess(summary_idx, todo_idx, "Summary before todo")
        self.assertLess(todo_idx, start_idx, "Todo before start")

    def test_todo_reminder_injected_when_todo_outside_window_start_outside_window(self):
        """Test todo reminder injection when both start and todo are outside window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Initial question", id=start_id),
            AssistantMessage(
                content="Creating todos",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Build feature", "status": "in_progress", "id": "1"}]},
                    )
                ],
            ),
        ]

        # Add many messages to push start and todo out of window
        for i in range(20):
            messages.append(HumanMessage(content=f"Question {i}", id=str(uuid4())))
            messages.append(AssistantMessage(content=f"Response {i}" * 50))

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have todo reminder
        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)
        self.assertIn("Build feature", todo_reminders[0].content)

    def test_todo_reminder_formats_todos_correctly(self):
        """Test that todo reminder formats different statuses correctly"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Creating todos",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={
                            "todos": [
                                {"content": "Pending task", "status": "pending", "id": "1"},
                                {"content": "In progress task", "status": "in_progress", "id": "2"},
                                {"content": "Completed task", "status": "completed", "id": "3"},
                            ]
                        },
                    )
                ],
            ),
            AssistantMessage(content="x" * 10000),  # Force no boundary
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)
        content = todo_reminders[0].content

        # Check status indicators
        self.assertIn("○ [pending] Pending task", content)
        self.assertIn("→ [in_progress] In progress task", content)
        self.assertIn("✓ [completed] Completed task", content)

    def test_todo_reminder_uses_last_todo_when_multiple_exist(self):
        """Test that only the last TODO_WRITE is used when multiple exist"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="First todo",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Old task", "status": "pending", "id": "1"}]},
                    )
                ],
            ),
            AssistantMessage(
                content="Second todo",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-2",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "New task", "status": "pending", "id": "2"}]},
                    )
                ],
            ),
            AssistantMessage(content="x" * 10000),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)

        # Should have the new task, not the old one
        self.assertIn("New task", todo_reminders[0].content)
        self.assertNotIn("Old task", todo_reminders[0].content)

    def test_todo_reminder_handles_empty_todos_list(self):
        """Test that empty todos list shows appropriate message"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Empty todo",
                tool_calls=[AssistantToolCall(id="todo-1", name=AssistantTool.TODO_WRITE, args={"todos": []})],
            ),
            AssistantMessage(content="x" * 10000),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 1)
        self.assertIn("empty", todo_reminders[0].content.lower())

    def test_todo_and_mode_reminder_both_injected(self):
        """Test that both todo and mode reminders are injected in correct order"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Todo",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Task", "status": "pending", "id": "1"}]},
                    )
                ],
            ),
            AssistantMessage(content="x" * 10000),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Find all three: summary, todo reminder, mode reminder
        summary_idx = next(i for i, msg in enumerate(result.messages) if msg.id == summary_id)
        todo_idx = next(
            i
            for i, msg in enumerate(result.messages)
            if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        )
        mode_idx = next(
            i
            for i, msg in enumerate(result.messages)
            if isinstance(msg, ContextMessage) and msg.id != summary_id and "product_analytics" in msg.content
        )

        # Verify order: summary → todo → mode
        self.assertLess(summary_idx, todo_idx)
        self.assertLess(todo_idx, mode_idx)

    def test_todo_reminder_only_no_mode_reminder(self):
        """Test that only todo reminder is inserted when mode is evident"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Question", id=start_id),
            AssistantMessage(
                content="Todo",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Task", "status": "pending", "id": "1"}]},
                    )
                ],
            ),
        ]

        # Add many messages to push todo out, but keep switch_mode in window
        for i in range(15):
            messages.append(HumanMessage(content=f"Question {i}", id=str(uuid4())))
            messages.append(AssistantMessage(content=f"Response {i}"))

        # Add switch_mode near the end (will be in window)
        messages.append(
            AssistantMessage(
                content="Switch mode",
                tool_calls=[
                    AssistantToolCall(id="switch-1", name=AssistantTool.SWITCH_MODE, args={"mode": "product_analytics"})
                ],
            )
        )
        messages.append(AssistantMessage(content="Response"))

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have todo reminder
        todo_reminders = [
            msg for msg in result.messages if isinstance(msg, HumanMessage) and "todo list" in msg.content.lower()
        ]
        self.assertGreater(len(todo_reminders), 0)

        # Should NOT have mode reminder (only summary context message)
        context_messages = [msg for msg in result.messages if isinstance(msg, ContextMessage)]
        mode_reminders = [msg for msg in context_messages if msg.id != summary_id]
        self.assertEqual(len(mode_reminders), 0)

    def test_mode_reminder_only_no_todo_reminder(self):
        """Test that only mode reminder is inserted when todo is in window"""
        start_id = str(uuid4())
        summary_id = str(uuid4())

        messages: list[AssistantMessageUnion] = [
            HumanMessage(content="Old question", id=str(uuid4())),
            AssistantMessage(content="Old response"),
            HumanMessage(content="Recent question", id=start_id),
            AssistantMessage(
                content="Todo",
                tool_calls=[
                    AssistantToolCall(
                        id="todo-1",
                        name=AssistantTool.TODO_WRITE,
                        args={"todos": [{"content": "Task", "status": "pending", "id": "1"}]},
                    )
                ],
            ),
            AssistantMessage(content="Response"),
        ]

        summary_message = ContextMessage(content="Summary", id=summary_id)

        result = self.window_manager.update_window(
            messages, summary_message, AgentMode.PRODUCT_ANALYTICS, start_id=start_id
        )

        # Should have mode reminder
        mode_reminders = [
            msg
            for msg in result.messages
            if isinstance(msg, ContextMessage) and msg.id != summary_id and "product_analytics" in msg.content
        ]
        self.assertEqual(len(mode_reminders), 1)

        # Should NOT have todo reminder (todo is in window)
        todo_reminders = [
            msg
            for msg in result.messages
            if isinstance(msg, HumanMessage) and msg.id != start_id and "todo list" in msg.content.lower()
        ]
        self.assertEqual(len(todo_reminders), 0)
