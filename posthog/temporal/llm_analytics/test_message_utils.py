"""Tests for message extraction utilities."""

from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages


class TestExtractTextFromMessages:
    def test_simple_string(self):
        """Test extraction from simple string"""
        result = extract_text_from_messages("Hello world")
        assert result == "Hello world"

    def test_empty_input(self):
        """Test extraction from empty/None input"""
        assert extract_text_from_messages(None) == ""
        assert extract_text_from_messages("") == ""
        assert extract_text_from_messages([]) == ""

    def test_openai_format(self):
        """Test extraction from OpenAI message format"""
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: What is 2+2?\nassistant: 4"

    def test_anthropic_format(self):
        """Test extraction from Anthropic message format with content blocks"""
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there"}],
            },
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: Hello\nassistant: Hi there"

    def test_mixed_content_blocks(self):
        """Test extraction from mixed content with text and other types"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "First part"},
                    {"type": "text", "text": "Second part"},
                ],
            }
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: First part Second part"

    def test_output_choices_format(self):
        """Test extraction from $ai_output_choices format (real PostHog events)"""
        messages = [
            {
                "content": "Looks like today weather decided to audition for a soap opera",
                "role": "assistant",
            }
        ]
        result = extract_text_from_messages(messages)
        assert "soap opera" in result
        assert "assistant:" in result

    def test_single_dict_message(self):
        """Test extraction from single dict (not in array)"""
        message = {"role": "user", "content": "Hello"}
        result = extract_text_from_messages(message)
        assert result == "Hello"
