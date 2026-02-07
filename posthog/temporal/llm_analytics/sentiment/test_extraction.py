"""Tests for sentiment text extraction utilities."""

from posthog.temporal.llm_analytics.sentiment.extraction import extract_user_messages, truncate_to_token_limit


class TestExtractUserMessages:
    def test_openai_format_filters_user_only(self):
        ai_input = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello, I need help"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "I'm frustrated with this feature"},
        ]
        result = extract_user_messages(ai_input)
        assert result == "Hello, I need help. I'm frustrated with this feature"

    def test_anthropic_format(self):
        ai_input = [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Hi"}]},
            {"role": "user", "content": [{"type": "text", "text": "Help me"}]},
        ]
        result = extract_user_messages(ai_input)
        assert result == "Hello. Help me"

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


class TestTruncateToTokenLimit:
    def test_short_text_unchanged(self):
        text = "Hello world"
        assert truncate_to_token_limit(text) == text

    def test_long_text_truncated(self):
        text = "x" * 2000
        result = truncate_to_token_limit(text)
        assert len(result) == 1500

    def test_exact_limit(self):
        text = "x" * 1500
        assert truncate_to_token_limit(text) == text

    def test_custom_limit(self):
        text = "x" * 100
        result = truncate_to_token_limit(text, max_chars=50)
        assert len(result) == 50
