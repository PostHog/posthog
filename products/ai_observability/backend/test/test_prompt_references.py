from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.prompt_references import PromptReference, parse_prompt_references


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
        ]
    )
    def test_parse(self, _name: str, text: str, expected: list[PromptReference]) -> None:
        assert parse_prompt_references(text) == expected
