from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage

from posthog.schema import AssistantMessage, AssistantToolCallMessage

from ee.hogai.utils.helpers import normalize_ai_message, should_output_assistant_message


class TestAssistantHelpers(BaseTest):
    def test_should_output_assistant_message(self):
        """
        Test that the should_output_assistant_message filter works correctly:
        - AssistantMessage with content should return True
        - Empty AssistantMessage should return False
        - AssistantToolCallMessage with UI payload should return True
        - AssistantToolCallMessage without UI payload should also return True (not filtered)
        """
        # Should return True: AssistantMessage with content
        message_with_content = AssistantMessage(content="This message has content", type="ai")
        self.assertTrue(should_output_assistant_message(message_with_content))

        # Should return False: Empty AssistantMessage
        empty_message = AssistantMessage(content="", type="ai")
        self.assertFalse(should_output_assistant_message(empty_message))

        # Should return True: AssistantToolCallMessage with UI payload
        tool_message_with_payload = AssistantToolCallMessage(
            content="Tool result", tool_call_id="123", type="tool", ui_payload={"some": "data"}
        )
        self.assertTrue(should_output_assistant_message(tool_message_with_payload))

        # Should return True: AssistantToolCallMessage without UI payload (not filtered by this function)
        tool_message_without_payload = AssistantToolCallMessage(
            content="Tool result", tool_call_id="456", type="tool", ui_payload=None
        )
        self.assertTrue(should_output_assistant_message(tool_message_without_payload))


class TestNormalizeAIMessage(BaseTest):
    def test_normalize_ai_message_with_string_content(self):
        """Test normalizing AIMessage with simple string content"""
        message = AIMessage(
            content="Hello world",
            tool_calls=[
                {"id": "call_1", "name": "test_tool", "args": {"param": "value"}},
                {"id": "call_2", "name": "another_tool", "args": {"x": 1, "y": 2}},
            ],
        )

        result = normalize_ai_message(message)

        self.assertIsInstance(result, AssistantMessage)
        self.assertEqual(result.content, "Hello world")
        self.assertEqual(result.type, "ai")
        self.assertIsNotNone(result.id)

        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 2)
        self.assertEqual(result.tool_calls[0].id, "call_1")
        self.assertEqual(result.tool_calls[0].name, "test_tool")
        self.assertEqual(result.tool_calls[0].args, {"param": "value"})
        self.assertEqual(result.tool_calls[1].id, "call_2")
        self.assertEqual(result.tool_calls[1].name, "another_tool")
        self.assertEqual(result.tool_calls[1].args, {"x": 1, "y": 2})

        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_no_tool_calls(self):
        """Test normalizing AIMessage without tool calls"""
        message = AIMessage(content="Simple message", tool_calls=[])

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "Simple message")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 0)
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_complex_content_text_only(self):
        """Test normalizing AIMessage with complex content containing only text blocks"""
        message = AIMessage(
            content=[
                "First text block",
                {"type": "text", "text": "Second text block"},
                "Third text block",
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        expected_content = "First text blockSecond text blockThird text block"
        self.assertEqual(result.content, expected_content)
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_with_thinking_content(self):
        """Test normalizing AIMessage with thinking blocks"""
        thinking_block = {"type": "thinking", "content": "Let me think about this..."}
        redacted_thinking_block = {"type": "redacted_thinking", "content": "Redacted thoughts"}

        message = AIMessage(
            content=[
                "Regular text",
                thinking_block,
                {"type": "text", "text": "More text"},
                redacted_thinking_block,
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "Regular textMore text")
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0], thinking_block)
        self.assertEqual(result.meta.thinking[1], redacted_thinking_block)

    def test_normalize_ai_message_with_mixed_content(self):
        """Test normalizing AIMessage with mixed content types including thinking"""
        message = AIMessage(
            content=[
                "Start text",
                {"type": "thinking", "reasoning": "Complex reasoning here"},
                {"type": "text", "text": "Middle text"},
                {"type": "other", "data": "should be ignored"},
                "End text",
                {"type": "redacted_thinking", "content": "Secret thoughts"},
            ],
            tool_calls=[{"id": "tool_1", "name": "search", "args": {"query": "test"}}],
        )

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "Start textMiddle textEnd text")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "search")

        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0]["type"], "thinking")
        self.assertEqual(result.meta.thinking[1]["type"], "redacted_thinking")

    def test_normalize_ai_message_empty_content_list(self):
        """Test normalizing AIMessage with empty content list"""
        message = AIMessage(content=[], tool_calls=[])

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNone(result.meta)

    def test_normalize_ai_message_only_thinking(self):
        """Test normalizing AIMessage with only thinking blocks"""
        message = AIMessage(
            content=[
                {"type": "thinking", "content": "First thought"},
                {"type": "redacted_thinking", "content": "Second thought"},
            ],
            tool_calls=[],
        )

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)

        # OpenAI format
        message = AIMessage(
            content=[], tool_calls=[], additional_kwargs={"reasoning": {"summary": [{"text": "Some thinking"}]}}
        )

        result = normalize_ai_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 1)
