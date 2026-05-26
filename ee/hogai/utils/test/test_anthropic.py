from posthog.test.base import BaseTest

from langchain_core.messages import HumanMessage
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantMessageMetadata

from ee.hogai.utils.anthropic import (
    add_cache_control,
    convert_assistant_message_to_anthropic_message,
    get_anthropic_thinking_from_assistant_message,
)


class TestAnthropicUtils(BaseTest):
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

        result = get_anthropic_thinking_from_assistant_message(message)

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
        self.assertEqual(message.content[0]["cache_control"], {"type": "ephemeral", "ttl": "5m"})

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
        self.assertEqual(message.content[1]["cache_control"], {"type": "ephemeral", "ttl": "5m"})

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
        self.assertEqual(message.content[1]["cache_control"], {"type": "ephemeral", "ttl": "5m"})

    def test_convert_assistant_message_without_source_has_no_provenance_note(self):
        message = AssistantMessage(content="Hello", id="1")
        result = convert_assistant_message_to_anthropic_message(message, {})
        self.assertEqual(len(result), 1)
        content = result[0].content
        assert isinstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "Hello"})

    def test_convert_assistant_message_with_slash_command_source_prepends_provenance_note(self):
        message = AssistantMessage(
            content="Current conversation: 5 credits",
            id="1",
            meta=AssistantMessageMetadata(source="slash_command:usage"),
        )
        result = convert_assistant_message_to_anthropic_message(message, {})
        self.assertEqual(len(result), 1)
        content = result[0].content
        assert isinstance(content, list)
        assert isinstance(content[0], dict)
        text = content[0]["text"]
        self.assertIn("/usage slash command", text)
        self.assertIn("deterministic PostHog code", text)
        self.assertIn("Current conversation: 5 credits", text)
        self.assertTrue(text.endswith("Current conversation: 5 credits"))

    def test_convert_assistant_message_with_unknown_source_has_no_provenance_note(self):
        message = AssistantMessage(
            content="Hello",
            id="1",
            meta=AssistantMessageMetadata(source="unknown_source"),
        )
        result = convert_assistant_message_to_anthropic_message(message, {})
        self.assertEqual(len(result), 1)
        content = result[0].content
        assert isinstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "Hello"})
