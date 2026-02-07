"""Tests for sentiment text extraction utilities."""

from posthog.temporal.llm_analytics.sentiment.constants import MAX_MESSAGE_CHARS, MAX_USER_MESSAGES
from posthog.temporal.llm_analytics.sentiment.extraction import (
    extract_user_messages,
    extract_user_messages_individually,
    truncate_to_token_limit,
)


class TestExtractUserMessages:
    def test_openai_format_filters_user_only(self):
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello, I need help"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "I'm frustrated with this feature"},
        ]
        result = extract_user_messages(ai_input)
        assert result == "Hello, I need help\n\n---\n\nI'm frustrated with this feature"

    def test_anthropic_format(self):
        ai_input = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
            {"role": "user", "content": [{"type": "text", "text": "Help me"}]},
        ]
        result = extract_user_messages(ai_input)
        assert result == "Hello\n\n---\n\nHelp me"

    def test_none_input(self):
        assert extract_user_messages(None) == ""

    def test_empty_list(self):
        assert extract_user_messages([]) == ""

    def test_empty_string(self):
        assert extract_user_messages("") == ""

    def test_string_input(self):
        assert extract_user_messages("raw text") == "raw text"

    def test_no_user_messages(self):
        ai_input = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "Hello!"},
        ]
        assert extract_user_messages(ai_input) == ""

    def test_empty_user_messages(self):
        ai_input = [
            {"role": "user", "content": ""},
            {"role": "user", "content": ""},
        ]
        assert extract_user_messages(ai_input) == ""

    def test_single_dict_user(self):
        assert extract_user_messages({"role": "user", "content": "Hello"}) == "Hello"

    def test_single_dict_non_user(self):
        assert extract_user_messages({"role": "system", "content": "Instructions"}) == ""

    def test_mixed_empty_and_nonempty(self):
        ai_input = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "Real message"},
        ]
        assert extract_user_messages(ai_input) == "Real message"


class TestExtractUserMessagesIndividually:
    def test_openai_format_returns_list(self):
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello, I need help"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "I'm frustrated with this feature"},
        ]
        result = extract_user_messages_individually(ai_input)
        assert result == ["Hello, I need help", "I'm frustrated with this feature"]

    def test_anthropic_format(self):
        ai_input = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
            {"role": "user", "content": [{"type": "text", "text": "Help me"}]},
        ]
        result = extract_user_messages_individually(ai_input)
        assert result == ["Hello", "Help me"]

    def test_none_input(self):
        assert extract_user_messages_individually(None) == []

    def test_empty_list(self):
        assert extract_user_messages_individually([]) == []

    def test_empty_string(self):
        assert extract_user_messages_individually("") == []

    def test_string_input(self):
        assert extract_user_messages_individually("raw text") == ["raw text"]

    def test_no_user_messages(self):
        ai_input = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "Hello!"},
        ]
        assert extract_user_messages_individually(ai_input) == []

    def test_empty_user_messages_filtered(self):
        ai_input = [
            {"role": "user", "content": ""},
            {"role": "user", "content": ""},
        ]
        assert extract_user_messages_individually(ai_input) == []

    def test_single_dict_user(self):
        assert extract_user_messages_individually({"role": "user", "content": "Hello"}) == ["Hello"]

    def test_single_dict_non_user(self):
        assert extract_user_messages_individually({"role": "system", "content": "Instructions"}) == []

    def test_mixed_empty_and_nonempty(self):
        ai_input = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "Real message"},
        ]
        assert extract_user_messages_individually(ai_input) == ["Real message"]

    def test_single_user_message(self):
        ai_input = [{"role": "user", "content": "Just one message"}]
        assert extract_user_messages_individually(ai_input) == ["Just one message"]

    def test_limits_to_last_n_messages(self):
        total = MAX_USER_MESSAGES + 10
        ai_input = [{"role": "user", "content": f"msg {i}"} for i in range(total)]
        result = extract_user_messages_individually(ai_input)
        assert len(result) == MAX_USER_MESSAGES
        assert result == [f"msg {i}" for i in range(total - MAX_USER_MESSAGES, total)]

    def test_exactly_max_messages(self):
        ai_input = [{"role": "user", "content": f"msg {i}"} for i in range(MAX_USER_MESSAGES)]
        result = extract_user_messages_individually(ai_input)
        assert len(result) == MAX_USER_MESSAGES

    def test_limit_applies_after_filtering(self):
        total = MAX_USER_MESSAGES + 10
        ai_input = []
        for i in range(total):
            ai_input.append({"role": "user", "content": f"user {i}"})
            ai_input.append({"role": "assistant", "content": f"assistant {i}"})
        result = extract_user_messages_individually(ai_input)
        assert len(result) == MAX_USER_MESSAGES
        assert result[0] == f"user {total - MAX_USER_MESSAGES}"
        assert result[-1] == f"user {total - 1}"


class TestTruncateToTokenLimit:
    def test_short_text_unchanged(self):
        text = "Hello world"
        assert truncate_to_token_limit(text) == text

    def test_long_text_keeps_tail(self):
        text = "HEAD" + "x" * (MAX_MESSAGE_CHARS + 500)
        result = truncate_to_token_limit(text)
        assert len(result) == MAX_MESSAGE_CHARS
        assert not result.startswith("HEAD")

    def test_exact_limit(self):
        text = "x" * MAX_MESSAGE_CHARS
        assert truncate_to_token_limit(text) == text

    def test_custom_limit_keeps_tail(self):
        text = "AAAA" + "B" * 96
        result = truncate_to_token_limit(text, max_chars=50)
        assert len(result) == 50
        assert result == "B" * 50
