from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scope_suggestions import sanitize_scopes


class TestSanitizeScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("drops_wildcard", ["*", "insight:read"], ["insight:read"]),
            ("drops_unknown_object", ["insight:read", "not_a_thing:read"], ["insight:read"]),
            ("drops_unknown_action", ["insight:admin", "insight:read"], ["insight:read"]),
            ("drops_privileged", ["llm_gateway:write", "insight:read"], ["insight:read"]),
            ("dedupes_and_keeps_order", ["query:read", "insight:read", "query:read"], ["query:read", "insight:read"]),
            ("trims_whitespace", [" insight:read "], ["insight:read"]),
            ("empty_stays_empty", [], []),
        ]
    )
    def test_sanitize_scopes(self, _name: str, suggested: list[str], expected: list[str]) -> None:
        assert sanitize_scopes(suggested) == expected
