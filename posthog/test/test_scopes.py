import runpy
from pathlib import Path

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.scopes import (
    ALL_SCOPES,
    ALWAYS_ALLOWED_SCOPES,
    API_SCOPE_ACTIONS,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    OAUTH_SCOPES_HIDDEN,
    PRIVILEGED_SCOPES,
    PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION,
    UNPRIVILEGED_SCOPES,
    downgrade_scopes_to_read_only,
    get_oauth_scopes_supported,
    get_scope_descriptions,
)

# Cases that need no database live in test_scopes_pure.py, so they run without
# Django database setup. Only add a class here when it needs a real database.


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


# sorted: parameterized bakes the iteration order into the test ids, and a frozenset
# iterates in hash order, which differs per process.
INTERNAL_SCOPE_CASES = [
    (f"{obj}:{action}",) for obj in sorted(INTERNAL_API_SCOPE_OBJECTS) for action in API_SCOPE_ACTIONS
]


class TestScopeSets(BaseTest):
    def test_all_scopes_matches_scope_descriptions_keys(self) -> None:
        self.assertEqual(ALL_SCOPES, frozenset(get_scope_descriptions().keys()))

    @parameterized.expand(INTERNAL_SCOPE_CASES)
    def test_all_scopes_excludes_internal_scope(self, scope: str) -> None:
        self.assertNotIn(scope, ALL_SCOPES)

    def test_privileged_scopes_subset_of_all_scopes(self) -> None:
        self.assertTrue(PRIVILEGED_SCOPES.issubset(ALL_SCOPES))
        self.assertIn("llm_gateway:read", PRIVILEGED_SCOPES)

    def test_unprivileged_scopes_excludes_privileged_and_hidden(self) -> None:
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(PRIVILEGED_SCOPES))
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(OAUTH_SCOPES_HIDDEN))

    @parameterized.expand([("openid",), ("profile",), ("email",)])
    def test_unprivileged_scopes_excludes_oidc(self, oidc: str) -> None:
        # OIDC scopes are accepted at /authorize independently of application.scopes;
        # they are not part of the UNPRIVILEGED broad-default set.
        self.assertNotIn(oidc, UNPRIVILEGED_SCOPES)

    @parameterized.expand(INTERNAL_SCOPE_CASES)
    def test_unprivileged_scopes_excludes_internal_scope(self, scope: str) -> None:
        self.assertNotIn(scope, UNPRIVILEGED_SCOPES)

    @parameterized.expand(
        [("insight:read",), ("dashboard:write",), ("query:read",), ("customer_task:read",), ("customer_task:write",)]
    )
    def test_unprivileged_scopes_covers_known_public_scope(self, scope: str) -> None:
        # Spot-check: a generic OAuth client should be able to request these.
        self.assertIn(scope, UNPRIVILEGED_SCOPES)

    def test_scopes_module_loadable_via_runpy_like_mcp_codegen(self) -> None:
        # MCP scope codegen at bin/build-mcp-oauth-scopes.py loads this module via
        # runpy.run_path (bypassing posthog/__init__.py which pulls in Django).
        # Mirror that mechanism here so the test actually catches a regression
        # where someone adds a Django-requiring import to posthog/scopes.py.
        # `import posthog.scopes` would not catch it — that runs __init__.py too.
        scopes_path = Path(__file__).resolve().parent.parent / "scopes.py"
        loaded = runpy.run_path(str(scopes_path))
        self.assertIn("UNPRIVILEGED_SCOPES", loaded)
        self.assertTrue(loaded["UNPRIVILEGED_SCOPES"])
        self.assertIn("llm_gateway:read", loaded["PRIVILEGED_SCOPES"])

    def test_oauth_scopes_supported_excludes_privileged_and_hidden(self) -> None:
        # Discovery metadata (/.well-known/oauth-authorization-server) must not
        # advertise privileged scopes (llm_gateway:*, admin-granted only) or
        # OAUTH_HIDDEN scopes — an OAuth client can't obtain them self-serve.
        supported = set(get_oauth_scopes_supported())
        self.assertTrue(supported.isdisjoint(PRIVILEGED_SCOPES))
        self.assertTrue(supported.isdisjoint(OAUTH_SCOPES_HIDDEN))
        self.assertNotIn("llm_gateway:read", supported)
        self.assertNotIn("llm_gateway:write", supported)

    def test_oauth_scopes_supported_includes_always_allowed_and_unprivileged(self) -> None:
        supported = set(get_oauth_scopes_supported())
        self.assertEqual(supported - ALWAYS_ALLOWED_SCOPES, UNPRIVILEGED_SCOPES)

    def test_project_secret_api_keys_exclude_user_bound_customer_task_scopes(self) -> None:
        # Customer task endpoints need a user for RBAC and activity attribution.
        self.assertNotIn(("customer_task", "read"), PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION)
        self.assertNotIn(("customer_task", "write"), PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION)

    def test_all_scope_objects_fit_in_oauthapplication_scopes_charfield(self) -> None:
        # OAuthApplication.scopes is ArrayField(CharField(max_length=100)), matching
        # PersonalAPIKey.scopes. Verify every `obj:action` string fits so admin-set
        # ceilings don't truncate.
        for scope in ALL_SCOPES:
            self.assertLessEqual(len(scope), 100, f"{scope} exceeds OAuthApplication.scopes CharField max_length=100")
