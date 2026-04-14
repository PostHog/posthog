"""Tests for message extraction utilities."""

import pytest

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

    @pytest.mark.parametrize(
        "label,messages,expected_substring",
        [
            (
                "anthropic_text_blocks",
                [{"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]}],
                "Hi there",
            ),
            (
                "openai_responses_api",
                [{"content": [{"annotations": [], "logprobs": [], "text": "Improving customer experiences."}]}],
                "Improving customer experiences",
            ),
            (
                "unknown_block_shape_fallback",
                [{"content": [{"some_unknown_key": "some_value", "another_key": 42}]}],
                "some_value",
            ),
            (
                "none_text_value",
                [{"content": [{"text": None, "annotations": []}]}],
                "None",
            ),
        ],
    )
    def test_content_block_formats(self, label, messages, expected_substring):
        result = extract_text_from_messages(messages)
        assert expected_substring in result
        assert result != ""

    def test_mixed_content_blocks(self):
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
        message = {"role": "user", "content": "Hello"}
        result = extract_text_from_messages(message)
        assert result == "Hello"
        assert result != ""
