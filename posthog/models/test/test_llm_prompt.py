from unittest import TestCase

from parameterized import parameterized

from posthog.models.llm_prompt import normalize_prompt_to_string


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
