from parameterized import parameterized

from posthog.temporal.llm_analytics.sentiment.extraction import (
    _is_tool_result_message,
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
            (
                "anthropic_tool_result_skipped",
                [
                    {"role": "user", "content": "tell me a joke"},
                    {"role": "assistant", "content": [{"type": "tool_use", "name": "joke_tool", "input": {}}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_01", "content": "Why did the chicken..."}
                        ],
                    },
                    {"role": "user", "content": "haha nice"},
                ],
                "tell me a joke\n\n---\n\nhaha nice",
            ),
            (
                "anthropic_multiple_tool_results_skipped",
                [
                    {"role": "user", "content": "do two things"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "content": "result 1"},
                            {"type": "tool_result", "tool_use_id": "t2", "content": "result 2"},
                        ],
                    },
                    {"role": "user", "content": "thanks"},
                ],
                "do two things\n\n---\n\nthanks",
            ),
        ]
    )
    def test_extract_user_messages(self, _name: str, ai_input, expected: str):
        assert extract_user_messages(ai_input) == expected


class TestExtractUserMessagesIndividually:
    @parameterized.expand(
        [
            ("none_input", None, []),
            ("empty_string", "", []),
            ("plain_string", "hello", [(0, "hello")]),
            ("single_user_dict", {"role": "user", "content": "hi"}, [(0, "hi")]),
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
                [(1, "a"), (3, "c")],
            ),
            ("empty_list", [], []),
            ("integer_input", 123, []),
            (
                "anthropic_tool_result_skipped",
                [
                    {"role": "user", "content": "tell me a joke"},
                    {"role": "assistant", "content": [{"type": "tool_use", "name": "joke_tool", "input": {}}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_01", "content": "Why did the chicken..."}
                        ],
                    },
                    {"role": "user", "content": "haha nice"},
                ],
                [(0, "tell me a joke"), (3, "haha nice")],
            ),
            (
                "anthropic_conversation_with_tool_results",
                [
                    {"role": "user", "content": "hi"},
                    {"role": "user", "content": "im sad"},
                    {"role": "user", "content": "tell me a joke"},
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Joke: ..."}],
                    },
                    {"role": "user", "content": "uh makes me sadder"},
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "Better joke: ..."}],
                    },
                    {"role": "user", "content": "haha ok thats better lol thanks"},
                    {"role": "user", "content": "bye"},
                ],
                [
                    (0, "hi"),
                    (1, "im sad"),
                    (2, "tell me a joke"),
                    (4, "uh makes me sadder"),
                    (6, "haha ok thats better lol thanks"),
                    (7, "bye"),
                ],
            ),
        ]
    )
    def test_extract_user_messages_individually(self, _name: str, ai_input, expected: list[tuple[int, str]]):
        assert extract_user_messages_individually(ai_input) == expected

    def test_limits_to_max_user_messages(self):
        from posthog.temporal.llm_analytics.sentiment.constants import MAX_USER_MESSAGES

        messages = [{"role": "user", "content": f"msg-{i}"} for i in range(MAX_USER_MESSAGES + 10)]
        result = extract_user_messages_individually(messages)
        assert len(result) == MAX_USER_MESSAGES
        # keeps the last N messages, with original indices preserved
        assert result[0] == (10, "msg-10")
        assert result[-1] == (MAX_USER_MESSAGES + 9, f"msg-{MAX_USER_MESSAGES + 9}")


class TestIsToolResultMessage:
    @parameterized.expand(
        [
            ("none", None, False),
            ("empty_string", "", False),
            ("plain_string", "hello", False),
            ("empty_list", [], False),
            ("text_blocks", [{"type": "text", "text": "hi"}], False),
            ("single_tool_result", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}], True),
            (
                "multiple_tool_results",
                [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "a"},
                    {"type": "tool_result", "tool_use_id": "t2", "content": "b"},
                ],
                True,
            ),
            (
                "mixed_text_and_tool_result",
                [{"type": "text", "text": "hi"}, {"type": "tool_result", "tool_use_id": "t1", "content": "a"}],
                False,
            ),
            ("dict_not_list", {"type": "tool_result", "tool_use_id": "t1", "content": "a"}, False),
        ]
    )
    def test_is_tool_result_message(self, _name: str, content, expected: bool):
        assert _is_tool_result_message(content) == expected


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
