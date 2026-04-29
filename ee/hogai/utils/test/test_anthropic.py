from posthog.test.base import BaseTest

from langchain_core.messages import HumanMessage
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantMessageMetadata

from ee.hogai.utils.anthropic import add_cache_control, get_anthropic_thinking_from_assistant_message


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

        assert result == expected

        # Verify it returns a copy, not the original
        if expected:
            assert result is not meta.thinking

    def test_add_cache_control_string_content(self):
        """Test adding cache control to message with string content"""
        message = HumanMessage(content="Test message")

        result = add_cache_control(message)

        assert result is message  # Should modify in place
        assert isinstance(message.content, list)
        assert len(message.content) == 1
        assert isinstance(message.content[0], dict)
        assert message.content[0]["type"] == "text"
        assert message.content[0]["text"] == "Test message"
        assert message.content[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}

    def test_add_cache_control_list_content_with_string_last(self):
        """Test adding cache control to message with list content ending in string"""
        message = HumanMessage(
            content=[
                {"type": "text", "text": "First part"},
                "Second part as string",
            ]
        )

        result = add_cache_control(message)

        assert result is message
        assert isinstance(message.content, list)
        assert len(message.content) == 2
        # First part unchanged
        assert isinstance(message.content[0], dict)
        assert message.content[0]["type"] == "text"
        assert message.content[0]["text"] == "First part"
        assert "cache_control" not in message.content[0]

        # Last part converted and cache control added
        assert isinstance(message.content[1], dict)
        assert message.content[1]["type"] == "text"
        assert message.content[1]["text"] == "Second part as string"
        assert message.content[1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}

    def test_add_cache_control_list_content_with_dict_last(self):
        """Test adding cache control to message with list content ending in dict"""
        message = HumanMessage(
            content=[
                {"type": "text", "text": "First part"},
                {"type": "image", "url": "http://example.com/image.jpg"},
            ]
        )

        result = add_cache_control(message)

        assert result is message
        assert isinstance(message.content, list)
        assert len(message.content) == 2
        # First part unchanged
        assert isinstance(message.content[0], dict)
        assert "cache_control" not in message.content[0]

        # Last part gets cache control added
        assert isinstance(message.content[1], dict)
        assert message.content[1]["type"] == "image"
        assert message.content[1]["url"] == "http://example.com/image.jpg"
        assert message.content[1]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
