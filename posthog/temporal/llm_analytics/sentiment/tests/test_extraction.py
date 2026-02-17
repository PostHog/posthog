from parameterized import parameterized

from posthog.temporal.llm_analytics.sentiment.extraction import (
    extract_user_messages,
    extract_user_messages_individually,
    truncate_to_token_limit,
)


class TestExtractUserMessages:
    @parameterized.expand(
        [
            ("none_input", None, ""),
            ("empty_string", "", ""),
            ("plain_string", "hello world", "hello world"),
            ("single_user_dict", {"role": "user", "content": "hi"}, "hi"),
            ("non_user_dict", {"role": "assistant", "content": "hi"}, ""),
            ("dict_no_role", {"content": "hi"}, ""),
            (
                "list_with_user_msgs",
                [
                    {"role": "user", "content": "msg-a"},
                    {"role": "assistant", "content": "reply"},
                    {"role": "user", "content": "msg-b"},
                ],
                "msg-a\n\n---\n\nmsg-b",
            ),
            ("list_no_user_msgs", [{"role": "assistant", "content": "reply"}], ""),
            ("empty_list", [], ""),
            (
                "anthropic_content_blocks",
                [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "block-a"}, {"type": "text", "text": "block-b"}],
                    }
                ],
                "block-a block-b",
            ),
            ("integer_input", 42, ""),
        ]
    )
    def test_extract_user_messages(self, _name: str, ai_input, expected: str):
        assert extract_user_messages(ai_input) == expected


class TestExtractUserMessagesIndividually:
    @parameterized.expand(
        [
            ("none_input", None, []),
            ("empty_string", "", []),
            ("plain_string", "hello", ["hello"]),
            ("single_user_dict", {"role": "user", "content": "hi"}, ["hi"]),
            ("non_user_dict", {"role": "system", "content": "hi"}, []),
            ("dict_empty_content", {"role": "user", "content": ""}, []),
            (
                "list_filters_to_user_only",
                [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                    {"role": "user", "content": "c"},
                ],
                ["a", "c"],
            ),
            ("empty_list", [], []),
            ("integer_input", 123, []),
        ]
    )
    def test_extract_user_messages_individually(self, _name: str, ai_input, expected: list[str]):
        assert extract_user_messages_individually(ai_input) == expected

    def test_limits_to_max_user_messages(self):
        from posthog.temporal.llm_analytics.sentiment.constants import MAX_USER_MESSAGES

        messages = [{"role": "user", "content": f"msg-{i}"} for i in range(MAX_USER_MESSAGES + 10)]
        result = extract_user_messages_individually(messages)
        assert len(result) == MAX_USER_MESSAGES
        # keeps the last N messages
        assert result[0] == f"msg-10"
        assert result[-1] == f"msg-{MAX_USER_MESSAGES + 9}"


class TestTruncateToTokenLimit:
    @parameterized.expand(
        [
            ("short_text", "hi", 100, "hi"),
            ("exact_limit", "abcde", 5, "abcde"),
            ("over_limit_takes_tail", "abcdefgh", 5, "defgh"),
            ("empty_string", "", 100, ""),
        ]
    )
    def test_truncation(self, _name: str, text: str, max_chars: int, expected: str):
        assert truncate_to_token_limit(text, max_chars=max_chars) == expected

    def test_default_max_chars_from_constants(self):
        from posthog.temporal.llm_analytics.sentiment.constants import MAX_MESSAGE_CHARS

        short_text = "x" * (MAX_MESSAGE_CHARS - 1)
        assert truncate_to_token_limit(short_text) == short_text

        long_text = "x" * (MAX_MESSAGE_CHARS + 100)
        assert len(truncate_to_token_limit(long_text)) == MAX_MESSAGE_CHARS
