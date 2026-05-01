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

    @pytest.mark.parametrize(
        "messages,expected_substrings",
        [
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "send_email",
                                    "arguments": '{"to": "user@example.com"}',
                                },
                            }
                        ],
                    }
                ],
                ["assistant:", "send_email", "user@example.com"],
                id="openai_tool_call_no_text_content",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": "On it.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "update_status",
                                    "arguments": '{"status": "ok"}',
                                },
                            }
                        ],
                    }
                ],
                ["On it.", "update_status", '{"status": "ok"}'],
                id="openai_tool_call_with_text_content",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "1", "type": "function", "function": {"name": "foo", "arguments": "{}"}},
                            {"id": "2", "type": "function", "function": {"name": "bar", "arguments": "{}"}},
                        ],
                    }
                ],
                ["foo", "bar"],
                id="multiple_tool_calls_in_one_message",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "1",
                                "type": "function",
                                "function": {"name": "foo", "arguments": {"x": 1}},
                            }
                        ],
                    }
                ],
                ["foo", '"x"', "1"],
                id="tool_call_with_dict_arguments",
            ),
        ],
    )
    def test_tool_call_rendering(self, messages, expected_substrings):
        result = extract_text_from_messages(messages)
        for substring in expected_substrings:
            assert substring in result, f"missing {substring!r} in {result!r}"

    def test_full_agentic_conversation_preserves_tool_calls_and_results(self):
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "Update placement status."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "update_placement_status",
                            "arguments": '{"status": "approved"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Status updated."},
            {"role": "assistant", "content": "Done."},
        ]
        result = extract_text_from_messages(messages)
        assert "system: You are an agent." in result
        assert "user: Update placement status." in result
        assert "update_placement_status" in result
        assert '{"status": "approved"}' in result
        assert "tool: Status updated." in result
        assert "assistant: Done." in result

    @pytest.mark.parametrize(
        "tool_calls",
        [
            pytest.param("not-a-list", id="not_a_list"),
            pytest.param([{"id": "1"}], id="missing_function"),
            pytest.param([{"function": {"name": ""}}], id="empty_name"),
            pytest.param([{"function": "broken"}], id="function_not_dict"),
            pytest.param(["broken"], id="tool_call_not_dict"),
        ],
    )
    def test_malformed_tool_calls_do_not_crash(self, tool_calls):
        messages = [{"role": "assistant", "content": "Hello", "tool_calls": tool_calls}]
        result = extract_text_from_messages(messages)
        assert "Hello" in result

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("", id="empty_string"),
            pytest.param(None, id="null"),
            pytest.param([], id="empty_list"),
        ],
    )
    def test_empty_content_with_role_preserves_slot(self, content):
        messages = [
            {"role": "user", "content": "did anything happen?"},
            {"role": "tool", "tool_call_id": "1", "content": content},
            {"role": "assistant", "content": "yes"},
        ]
        result = extract_text_from_messages(messages)
        assert "user: did anything happen?" in result
        assert "tool:" in result
        assert "assistant: yes" in result

    def test_completely_empty_message_is_skipped(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {},
            {"role": "assistant", "content": "Hello"},
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: Hi\nassistant: Hello"

    def test_single_dict_renders_tool_calls(self):
        message = {
            "role": "assistant",
            "content": "Calling the tool now.",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "foo", "arguments": '{"x": 1}'}}],
        }
        result = extract_text_from_messages(message)
        assert "Calling the tool now." in result
        assert "foo" in result
        assert '{"x": 1}' in result

    def test_single_dict_with_only_tool_calls(self):
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "send_email", "arguments": "{}"}}],
        }
        result = extract_text_from_messages(message)
        assert "send_email" in result
