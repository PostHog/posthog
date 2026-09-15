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
        ]
    )
    def test_parse(self, _name: str, text: str, expected: list[PromptReference]) -> None:
        assert parse_prompt_references(text) == expected
