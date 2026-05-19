from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.scopes import (
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    downgrade_scopes_to_read_only,
)


class TestDowngradeScopesToReadOnly(BaseTest):
    @parameterized.expand(
        [
            ("empty_string", "", ""),
            ("single_read_passthrough", "feature_flag:read", "feature_flag:read"),
            ("single_write_downgraded", "feature_flag:write", "feature_flag:read"),
            ("oidc_passthrough", "openid profile email", "openid profile email"),
            (
                "mixed_read_write_dedupe",
                "feature_flag:read feature_flag:write organization:write",
                "feature_flag:read organization:read",
            ),
            (
                "order_preserved_first_seen",
                "organization:write feature_flag:write",
                "organization:read feature_flag:read",
            ),
        ]
    )
    def test_basic_cases(self, _name: str, given: str, expected: str) -> None:
        self.assertEqual(downgrade_scopes_to_read_only(given), expected)

    def test_wildcard_expands_to_all_public_read_scopes(self) -> None:
        result = downgrade_scopes_to_read_only("*").split()
        expected = [
            f"{obj}:read"
            for obj in API_SCOPE_OBJECTS
            if obj not in INTERNAL_API_SCOPE_OBJECTS and obj not in OAUTH_HIDDEN_SCOPE_OBJECTS
        ]
        self.assertEqual(result, expected)
        # Sanity: no write scope, no internal scope, no hidden scope leaked through.
        for scope in result:
            self.assertFalse(scope.endswith(":write"), f"{scope} should have been read-only")
        for internal in INTERNAL_API_SCOPE_OBJECTS:
            self.assertNotIn(f"{internal}:read", result)
        for hidden in OAUTH_HIDDEN_SCOPE_OBJECTS:
            self.assertNotIn(f"{hidden}:read", result)

    def test_wildcard_combined_with_other_scopes_dedupes(self) -> None:
        # `*` already covers feature_flag:read — passing both must not duplicate the entry.
        result = downgrade_scopes_to_read_only("feature_flag:write * openid").split()
        self.assertEqual(result.count("feature_flag:read"), 1)
        self.assertIn("openid", result)

    def test_wildcard_only_token(self) -> None:
        # Bare `*` alone is the OAuth full-access shorthand and must NOT pass through.
        self.assertNotIn(":write", downgrade_scopes_to_read_only("*"))
        self.assertNotEqual(downgrade_scopes_to_read_only("*"), "*")
