from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend import prompt_references
from products.ai_observability.backend.prompt_references import PromptReference, parse_prompt_references

RESOLVER = "products.ai_observability.backend.prompt_references"


class TestParsePromptReferences(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "version_pin",
                "Intro @@@prompt:name=guardrails|version=3@@@ outro",
                [PromptReference(name="guardrails", version=3, label=None)],
            ),
            (
                "label_follow",
                "@@@prompt:name=guardrails|label=production@@@",
                [PromptReference(name="guardrails", version=None, label="production")],
            ),
            (
                "multiple_in_order_with_duplicates",
                "@@@prompt:name=a|version=1@@@ x @@@prompt:name=b|label=prod@@@ y @@@prompt:name=a|version=1@@@",
                [
                    PromptReference(name="a", version=1, label=None),
                    PromptReference(name="b", version=None, label="prod"),
                    PromptReference(name="a", version=1, label=None),
                ],
            ),
            ("no_tags", "Just {{variables}} and plain text", []),
            ("bare_name_not_a_reference", "@@@prompt:name=guardrails@@@", []),
            ("missing_value_not_a_reference", "@@@prompt:name=guardrails|version=@@@", []),
            ("uppercase_label_not_a_reference", "@@@prompt:name=guardrails|label=Production@@@", []),
            ("name_with_invalid_chars_not_a_reference", "@@@prompt:name=guard.rails|version=1@@@", []),
            ("unterminated_not_a_reference", "@@@prompt:name=guardrails|version=1", []),
            (
                "name_at_column_limit",
                f"@@@prompt:name={'a' * 255}|version=1@@@",
                [PromptReference(name="a" * 255, version=1, label=None)],
            ),
            ("name_over_column_limit_not_a_reference", f"@@@prompt:name={'a' * 256}|version=1@@@", []),
            (
                "label_at_column_limit",
                f"@@@prompt:name=guardrails|label={'b' * 128}@@@",
                [PromptReference(name="guardrails", version=None, label="b" * 128)],
            ),
            ("label_over_column_limit_not_a_reference", f"@@@prompt:name=guardrails|label={'b' * 129}@@@", []),
            (
                "version_at_digit_limit",
                "@@@prompt:name=guardrails|version=999999999@@@",
                [PromptReference(name="guardrails", version=999_999_999, label=None)],
            ),
            ("version_over_digit_limit_not_a_reference", "@@@prompt:name=guardrails|version=9999999999@@@", []),
            ("version_zero_not_a_reference", "@@@prompt:name=guardrails|version=0@@@", []),
            ("version_with_leading_zero_not_a_reference", "@@@prompt:name=guardrails|version=03@@@", []),
        ]
    )
    def test_parse(self, _name: str, text: str, expected: list[PromptReference]) -> None:
        assert parse_prompt_references(text) == expected


class TestResolvePromptReferences(SimpleTestCase):
    def setUp(self) -> None:
        self.team = MagicMock()

    def test_returns_content_unchanged_when_no_references(self) -> None:
        with patch(f"{RESOLVER}.get_prompt_by_name_from_cache") as cache:
            result = prompt_references.resolve_prompt_references(self.team, "plain prompt, no tags")
        assert result == "plain prompt, no tags"
        cache.assert_not_called()

    @patch(f"{RESOLVER}.get_prompt_by_name_from_cache")
    def test_splices_referenced_content(self, cache: MagicMock) -> None:
        cache.return_value = {"prompt": "CHILD", "version": 2}
        result = prompt_references.resolve_prompt_references(self.team, "before @@@prompt:name=foo|label=live@@@ after")
        assert result == "before CHILD after"

    @patch(f"{RESOLVER}.get_prompt_by_name_from_cache")
    def test_returns_none_when_reference_unresolvable(self, cache: MagicMock) -> None:
        # A referenced prompt that holds a tag of its own can't be spliced in; the caller
        # must fall back to its default rather than send a raw tag to the model.
        cache.return_value = {"prompt": "nested @@@prompt:name=bar|label=live@@@", "version": 1}
        result = prompt_references.resolve_prompt_references(self.team, "before @@@prompt:name=foo|label=live@@@ after")
        assert result is None
