from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage, HumanMessage
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantMessageMetadata

from ee.hogai.utils.anthropic import (
    add_cache_control,
    get_thinking_from_assistant_message,
    normalize_ai_anthropic_message,
)


class TestAnthropicUtils(BaseTest):
    def test_normalize_ai_anthropic_message_with_string_content(self):
        """Test normalizing AIMessage with simple string content"""
        message = AIMessage(
            content="Hello world",
            tool_calls=[
                {"id": "call_1", "name": "test_tool", "args": {"param": "value"}},
                {"id": "call_2", "name": "another_tool", "args": {"x": 1, "y": 2}},
            ],
        )

        result = normalize_ai_anthropic_message(message)

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

    def test_normalize_ai_anthropic_message_with_no_tool_calls(self):
        """Test normalizing AIMessage without tool calls"""
        message = AIMessage(content="Simple message", tool_calls=[])

        result = normalize_ai_anthropic_message(message)

        self.assertEqual(result.content, "Simple message")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 0)
        self.assertIsNone(result.meta)

    def test_normalize_ai_anthropic_message_with_complex_content_text_only(self):
        """Test normalizing AIMessage with complex content containing only text blocks"""
        message = AIMessage(
            content=[
                "First text block",
                {"type": "text", "text": "Second text block"},
                "Third text block",
            ],
            tool_calls=[],
        )

        result = normalize_ai_anthropic_message(message)

        expected_content = "First text block\nSecond text block\nThird text block"
        self.assertEqual(result.content, expected_content)
        self.assertIsNone(result.meta)

    def test_normalize_ai_anthropic_message_with_thinking_content(self):
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

        result = normalize_ai_anthropic_message(message)

        self.assertEqual(result.content, "Regular text\nMore text")
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0], thinking_block)
        self.assertEqual(result.meta.thinking[1], redacted_thinking_block)

    def test_normalize_ai_anthropic_message_with_mixed_content(self):
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

        result = normalize_ai_anthropic_message(message)

        self.assertEqual(result.content, "Start text\nMiddle text\nEnd text")
        assert isinstance(result.tool_calls, list)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "search")

        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)
        self.assertEqual(result.meta.thinking[0]["type"], "thinking")
        self.assertEqual(result.meta.thinking[1]["type"], "redacted_thinking")

    def test_normalize_ai_anthropic_message_empty_content_list(self):
        """Test normalizing AIMessage with empty content list"""
        message = AIMessage(content=[], tool_calls=[])

        result = normalize_ai_anthropic_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNone(result.meta)

    def test_normalize_ai_anthropic_message_only_thinking(self):
        """Test normalizing AIMessage with only thinking blocks"""
        message = AIMessage(
            content=[
                {"type": "thinking", "content": "First thought"},
                {"type": "redacted_thinking", "content": "Second thought"},
            ],
            tool_calls=[],
        )

        result = normalize_ai_anthropic_message(message)

        self.assertEqual(result.content, "")
        self.assertIsNotNone(result.meta)
        assert result.meta is not None
        assert result.meta.thinking is not None
        self.assertEqual(len(result.meta.thinking), 2)

    @parameterized.expand(
        [
            (None, []),
            (AssistantMessageMetadata(thinking=None), []),
            (AssistantMessageMetadata(thinking=[]), []),
            (
                AssistantMessageMetadata(thinking=[{"type": "thinking", "content": "test"}]),
                [{"type": "thinking", "content": "test"}],
            ),
            (
                AssistantMessageMetadata(
                    thinking=[
                        {"type": "thinking", "content": "first"},
                        {"type": "redacted_thinking", "content": "second"},
                    ]
                ),
                [{"type": "thinking", "content": "first"}, {"type": "redacted_thinking", "content": "second"}],
            ),
        ]
    )
    def test_get_thinking_from_assistant_message(self, meta, expected):
        """Test extracting thinking from AssistantMessage"""
        message = AssistantMessage(content="test", meta=meta)

        result = get_thinking_from_assistant_message(message)

        self.assertEqual(result, expected)

        # Verify it returns a copy, not the original
        if expected:
            self.assertIsNot(result, meta.thinking)

    def test_add_cache_control_string_content(self):
        """Test adding cache control to message with string content"""
        message = HumanMessage(content="Test message")

        result = add_cache_control(message)

        self.assertIs(result, message)  # Should modify in place
        assert isinstance(message.content, list)
        self.assertEqual(len(message.content), 1)
        assert isinstance(message.content[0], dict)
        self.assertEqual(message.content[0]["type"], "text")
        self.assertEqual(message.content[0]["text"], "Test message")
        self.assertEqual(message.content[0]["cache_control"], {"type": "ephemeral"})

    def test_add_cache_control_list_content_with_string_last(self):
        """Test adding cache control to message with list content ending in string"""
        message = HumanMessage(
            content=[
                {"type": "text", "text": "First part"},
                "Second part as string",
            ]
        )

        result = add_cache_control(message)

        self.assertIs(result, message)
        assert isinstance(message.content, list)
        self.assertEqual(len(message.content), 2)
        # First part unchanged
        assert isinstance(message.content[0], dict)
        self.assertEqual(message.content[0]["type"], "text")
        self.assertEqual(message.content[0]["text"], "First part")
        self.assertNotIn("cache_control", message.content[0])

        # Last part converted and cache control added
        assert isinstance(message.content[1], dict)
        self.assertEqual(message.content[1]["type"], "text")
        self.assertEqual(message.content[1]["text"], "Second part as string")
        self.assertEqual(message.content[1]["cache_control"], {"type": "ephemeral"})

    def test_add_cache_control_list_content_with_dict_last(self):
        """Test adding cache control to message with list content ending in dict"""
        message = HumanMessage(
            content=[
                {"type": "text", "text": "First part"},
                {"type": "image", "url": "http://example.com/image.jpg"},
            ]
        )

        result = add_cache_control(message)

        self.assertIs(result, message)
        assert isinstance(message.content, list)
        self.assertEqual(len(message.content), 2)
        # First part unchanged
        assert isinstance(message.content[0], dict)
        self.assertNotIn("cache_control", message.content[0])

        # Last part gets cache control added
        assert isinstance(message.content[1], dict)
        self.assertEqual(message.content[1]["type"], "image")
        self.assertEqual(message.content[1]["url"], "http://example.com/image.jpg")
        self.assertEqual(message.content[1]["cache_control"], {"type": "ephemeral"})
