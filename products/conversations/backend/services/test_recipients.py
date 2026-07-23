from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.services.recipients import MAX_EXTRA_RECIPIENTS, normalize_recipients


class TestNormalizeRecipients(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, [], []),
            ("empty", [], [], []),
            ("passthrough", ["a@x.com", "b@x.com"], [], ["a@x.com", "b@x.com"]),
            ("dedupe_case_insensitive", ["A@x.com", "a@x.com"], [], ["A@x.com"]),
            ("drops_invalid", ["good@x.com", "not-an-email", ""], [], ["good@x.com"]),
            ("excludes_primary_case_insensitive", ["A@x.com", "b@x.com"], ["a@x.com"], ["b@x.com"]),
            ("ignores_non_strings", ["a@x.com", 123, None], [], ["a@x.com"]),
            ("trims_whitespace", ["  a@x.com  "], [], ["a@x.com"]),
        ]
    )
    def test_normalize(self, _name: str, values: object, exclude: list[str], expected: list[str]) -> None:
        assert normalize_recipients(values, exclude=exclude) == expected  # type: ignore[arg-type]

    def test_caps_recipient_count(self) -> None:
        values = [f"user{i}@example.com" for i in range(MAX_EXTRA_RECIPIENTS + 5)]
        result = normalize_recipients(values)
        assert len(result) == MAX_EXTRA_RECIPIENTS
