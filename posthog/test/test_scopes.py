import sys
import subprocess

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.scopes import (
    ALL_SCOPES,
    API_SCOPE_OBJECTS,
    HIDDEN_SCOPES,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    PRIVILEGED_SCOPES,
    UNPRIVILEGED_SCOPES,
    downgrade_scopes_to_read_only,
    get_scope_descriptions,
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


class TestScopeSets(BaseTest):
    def test_all_scopes_matches_scope_descriptions_keys(self) -> None:
        self.assertEqual(ALL_SCOPES, frozenset(get_scope_descriptions().keys()))

    def test_all_scopes_contains_known_strings(self) -> None:
        for scope in ("insight:read", "insight:write", "llm_gateway:read", "llm_gateway:write"):
            self.assertIn(scope, ALL_SCOPES)

    def test_all_scopes_excludes_internal(self) -> None:
        for obj in INTERNAL_API_SCOPE_OBJECTS:
            self.assertNotIn(f"{obj}:read", ALL_SCOPES)
            self.assertNotIn(f"{obj}:write", ALL_SCOPES)

    def test_privileged_scopes_subset_of_all_scopes(self) -> None:
        self.assertTrue(PRIVILEGED_SCOPES.issubset(ALL_SCOPES))
        self.assertIn("llm_gateway:read", PRIVILEGED_SCOPES)

    def test_hidden_scopes_expands_oauth_hidden_objects_to_strings(self) -> None:
        # HIDDEN_SCOPES is the `obj:action` STRING form of OAUTH_HIDDEN_SCOPE_OBJECTS,
        # used by UNPRIVILEGED_SCOPES set arithmetic.
        expected = frozenset(f"{obj}:{action}" for obj in OAUTH_HIDDEN_SCOPE_OBJECTS for action in ("read", "write"))
        self.assertEqual(HIDDEN_SCOPES, expected)

    def test_unprivileged_scopes_excludes_privileged_and_hidden(self) -> None:
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(PRIVILEGED_SCOPES))
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(HIDDEN_SCOPES))

    def test_unprivileged_scopes_subset_of_all_scopes(self) -> None:
        self.assertTrue(UNPRIVILEGED_SCOPES.issubset(ALL_SCOPES))

    def test_unprivileged_scopes_excludes_oidc(self) -> None:
        # OIDC scopes are accepted at /authorize independently of application.scopes;
        # they are not part of the UNPRIVILEGED broad-default set.
        for oidc in ("openid", "profile", "email"):
            self.assertNotIn(oidc, UNPRIVILEGED_SCOPES)

    def test_unprivileged_scopes_excludes_internal(self) -> None:
        for obj in INTERNAL_API_SCOPE_OBJECTS:
            self.assertNotIn(f"{obj}:read", UNPRIVILEGED_SCOPES)
            self.assertNotIn(f"{obj}:write", UNPRIVILEGED_SCOPES)

    def test_unprivileged_scopes_covers_known_public_scopes(self) -> None:
        # Spot-check: public scopes a generic OAuth client should be able to request.
        for scope in ("insight:read", "dashboard:write", "query:read"):
            self.assertIn(scope, UNPRIVILEGED_SCOPES)

    def test_scopes_module_importable_without_django(self) -> None:
        # MCP scope codegen (bin/build-mcp-oauth-scopes.py) imports posthog.scopes
        # without Django setup. Verify nothing in the new constants pulls Django in.
        result = subprocess.run(
            [sys.executable, "-c", "import posthog.scopes; assert posthog.scopes.UNPRIVILEGED_SCOPES"],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": ":".join(sys.path)},
        )
        self.assertEqual(result.returncode, 0, f"stdout={result.stdout} stderr={result.stderr}")

    def test_all_scope_objects_fit_in_oauthapplication_scopes_charfield(self) -> None:
        # OAuthApplication.scopes is ArrayField(CharField(max_length=64)). Make sure
        # every `obj:action` string fits, so admin-set ceilings don't truncate.
        for scope in ALL_SCOPES:
            self.assertLessEqual(len(scope), 64, f"{scope} exceeds OAuthApplication.scopes CharField max_length=64")
