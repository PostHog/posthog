from unittest import TestCase

from parameterized import parameterized

from posthog.models.llm_prompt import get_prompt_outline, normalize_prompt_to_string


class TestNormalizePromptToString(TestCase):
    @parameterized.expand(
        [
            ("plain_string", "hello world", "hello world"),
            ("empty_string", "", ""),
            ("object", {"role": "system", "content": "hi"}, '{"role": "system", "content": "hi"}'),
            ("array", [{"role": "user", "content": "hi"}], '[{"role": "user", "content": "hi"}]'),
            ("number", 42, "42"),
            ("boolean", True, "true"),
            ("null", None, "null"),
            ("unicode", {"text": "héllo 🌍"}, '{"text": "héllo 🌍"}'),
        ]
    )
    def test_normalize_prompt_to_string(self, _name: str, value: object, expected: str) -> None:
        assert normalize_prompt_to_string(value) == expected


class TestGetPromptOutline(TestCase):
    @parameterized.expand(
        [
            ("empty_string", "", []),
            ("no_headings", "just some text\nwith two lines", []),
            (
                "flat_h1s",
                "# First\ncontent\n# Second",
                [{"level": 1, "text": "First"}, {"level": 1, "text": "Second"}],
            ),
            (
                "nested_levels",
                "# Role\n## Tools\n### Search\n## Output",
                [
                    {"level": 1, "text": "Role"},
                    {"level": 2, "text": "Tools"},
                    {"level": 3, "text": "Search"},
                    {"level": 2, "text": "Output"},
                ],
            ),
            (
                "preserves_markdown_in_text",
                "# Heading with [link](https://example.com)",
                [{"level": 1, "text": "Heading with [link](https://example.com)"}],
            ),
            (
                "strips_atx_close_preceded_by_whitespace",
                "# Heading ###",
                [{"level": 1, "text": "Heading"}],
            ),
            (
                "preserves_literal_hash_suffix_in_text",
                "## C#\n# F#\n# Heading#",
                [
                    {"level": 2, "text": "C#"},
                    {"level": 1, "text": "F#"},
                    {"level": 1, "text": "Heading#"},
                ],
            ),
            (
                "preserves_inline_hashes",
                "# Heading has # inline",
                [{"level": 1, "text": "Heading has # inline"}],
            ),
            (
                "ignores_inline_hashes",
                "not a heading # inline",
                [],
            ),
            (
                "ignores_deeper_than_h6",
                "####### too deep\n# real",
                [{"level": 1, "text": "real"}],
            ),
            (
                "handles_adversarial_whitespace_runs_without_hanging",
                "# x" + (" " * 5000) + "!",
                [{"level": 1, "text": "x" + (" " * 5000) + "!"}],
            ),
            ("json_array_payload", [{"role": "user", "content": "hi"}], []),
            ("none_payload", None, []),
        ]
    )
    def test_get_prompt_outline(self, _name: str, value: object, expected: list[dict[str, object]]) -> None:
        assert get_prompt_outline(value) == expected
