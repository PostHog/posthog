import runpy
from pathlib import Path

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scopes import (
    ALL_SCOPES,
    API_SCOPE_ACTIONS,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPES,
    OIDC_SCOPES,
    PRIVILEGED_SCOPES,
    UNPRIVILEGED_SCOPES,
    downgrade_scopes_to_read_only,
    effective_ceiling,
    filter_to_unprivileged_scopes,
    get_oauth_scopes_supported,
    get_scope_descriptions,
    narrow_scopes_to_ceiling,
    scopes_outside_ceiling,
    scopes_within_ceiling,
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


class TestScopeSets(BaseTest):
    def test_all_scopes_matches_scope_descriptions_keys(self) -> None:
        self.assertEqual(ALL_SCOPES, frozenset(get_scope_descriptions().keys()))

    @parameterized.expand([(f"{obj}:{action}",) for obj in INTERNAL_API_SCOPE_OBJECTS for action in API_SCOPE_ACTIONS])
    def test_all_scopes_excludes_internal_scope(self, scope: str) -> None:
        self.assertNotIn(scope, ALL_SCOPES)

    def test_privileged_scopes_subset_of_all_scopes(self) -> None:
        self.assertTrue(PRIVILEGED_SCOPES.issubset(ALL_SCOPES))
        self.assertIn("llm_gateway:read", PRIVILEGED_SCOPES)

    def test_unprivileged_scopes_excludes_privileged_and_hidden(self) -> None:
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(PRIVILEGED_SCOPES))
        self.assertTrue(UNPRIVILEGED_SCOPES.isdisjoint(OAUTH_HIDDEN_SCOPES))

    @parameterized.expand([("openid",), ("profile",), ("email",)])
    def test_unprivileged_scopes_excludes_oidc(self, oidc: str) -> None:
        # OIDC scopes are accepted at /authorize independently of application.scopes;
        # they are not part of the UNPRIVILEGED broad-default set.
        self.assertNotIn(oidc, UNPRIVILEGED_SCOPES)

    @parameterized.expand([(f"{obj}:{action}",) for obj in INTERNAL_API_SCOPE_OBJECTS for action in API_SCOPE_ACTIONS])
    def test_unprivileged_scopes_excludes_internal_scope(self, scope: str) -> None:
        self.assertNotIn(scope, UNPRIVILEGED_SCOPES)

    @parameterized.expand([("insight:read",), ("dashboard:write",), ("query:read",)])
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
        self.assertTrue(supported.isdisjoint(OAUTH_HIDDEN_SCOPES))
        self.assertNotIn("llm_gateway:read", supported)
        self.assertNotIn("llm_gateway:write", supported)

    def test_oauth_scopes_supported_includes_oidc_and_unprivileged(self) -> None:
        supported = set(get_oauth_scopes_supported())
        for oidc in OIDC_SCOPES:
            self.assertIn(oidc, supported)
        self.assertEqual(supported - set(OIDC_SCOPES), UNPRIVILEGED_SCOPES)

    def test_all_scope_objects_fit_in_oauthapplication_scopes_charfield(self) -> None:
        # OAuthApplication.scopes is ArrayField(CharField(max_length=100)), matching
        # PersonalAPIKey.scopes. Verify every `obj:action` string fits so admin-set
        # ceilings don't truncate.
        for scope in ALL_SCOPES:
            self.assertLessEqual(len(scope), 100, f"{scope} exceeds OAuthApplication.scopes CharField max_length=100")


class TestGetOAuthScopesSupported(SimpleTestCase):
    def test_signal_scout_internal_write_is_not_advertised(self) -> None:
        # Security invariant — the scout sandbox token carries `signal_scout_internal:write`
        # but is minted by direct DB insert (posthog/temporal/oauth.py), never via /authorize.
        # Advertising it in OAuth metadata would let any OAuth client request it via user
        # consent, a durable prompt-injection vector (scratchpad rows are read verbatim into
        # every subsequent run's prompt). It must NOT appear in the advertised scope set.
        assert "signal_scout_internal:write" not in get_oauth_scopes_supported()
        assert "signal_scout_internal:read" not in get_oauth_scopes_supported()

    def test_internal_scopes_are_not_advertised(self) -> None:
        advertised = set(get_oauth_scopes_supported())
        for obj in INTERNAL_API_SCOPE_OBJECTS:
            for action in ("read", "write"):
                assert f"{obj}:{action}" not in advertised, (
                    f"{obj}:{action} is in INTERNAL_API_SCOPE_OBJECTS but is being advertised in "
                    "OAuth metadata — internal scopes must never be advertised or user-grantable."
                )

    def test_oidc_scopes_are_advertised(self) -> None:
        scopes = get_oauth_scopes_supported()
        for oidc in ("openid", "profile", "email"):
            assert oidc in scopes


class TestGetScopeDescriptions(SimpleTestCase):
    @parameterized.expand(
        [
            ("signal_scout_internal:read",),
            ("signal_scout_internal:write",),
        ]
    )
    def test_signal_scout_internal_scopes_are_not_pak_descriptions(self, scope: str) -> None:
        # Critical security invariant — PAK validation reads from `get_scope_descriptions()`
        # and must reject `signal_scout_internal` (it's a prompt-injection vector if
        # user-grantable: scratchpad rows are read verbatim into every subsequent scout
        # run's prompt).
        assert scope not in get_scope_descriptions()

    def test_all_non_internal_objects_get_pak_descriptions(self) -> None:
        descriptions = get_scope_descriptions()
        for obj in API_SCOPE_OBJECTS:
            if obj in INTERNAL_API_SCOPE_OBJECTS:
                continue
            for action in ("read", "write"):
                assert f"{obj}:{action}" in descriptions


class TestScopesWithinCeiling(SimpleTestCase):
    @parameterized.expand(
        [
            ("subset_of_explicit_ceiling", ["query:read"], ["query:read", "insight:read"], True),
            ("outside_explicit_ceiling", ["insight:write"], ["query:read"], False),
            ("empty_request_always_allowed", [], ["query:read"], True),
            ("privileged_rejected_without_ceiling", ["llm_gateway:read"], [], False),
            ("privileged_allowed_when_in_ceiling", ["llm_gateway:read"], ["llm_gateway:read"], True),
            ("wildcard_rejected_under_explicit_ceiling", ["*"], ["query:read"], False),
            # Provisioning never grandfathered `*`; an unseeded ceiling must not grant it.
            ("wildcard_rejected_under_empty_ceiling", ["*"], [], False),
            ("unprivileged_allowed_under_empty_ceiling", ["query:read", "insight:write"], [], True),
            # `@default` sentinel: the unprivileged default plus the other listed scopes.
            ("default_sentinel_grants_unprivileged", ["query:read", "insight:write"], ["@default"], True),
            (
                "default_sentinel_grants_listed_privileged_extra",
                ["llm_gateway:read", "query:read"],
                ["@default", "llm_gateway:read"],
                True,
            ),
            (
                "default_sentinel_rejects_unlisted_privileged",
                ["llm_gateway:write"],
                ["@default", "llm_gateway:read"],
                False,
            ),
            ("wildcard_rejected_under_default_sentinel", ["*"], ["@default"], False),
            ("sentinel_itself_not_grantable", ["@default"], ["@default"], False),
            ("default_sentinel_tolerates_whitespace", ["query:read", "insight:write"], [" @default "], True),
        ]
    )
    def test_resolution(self, _name: str, requested: list[str], app_scopes: list[str], expected: bool) -> None:
        assert scopes_within_ceiling(requested, app_scopes) is expected

    @parameterized.expand(
        [
            ("openid_and_introspection", ["openid", "introspection"], ["query:read"]),
            ("email_under_empty_ceiling", ["email"], []),
        ]
    )
    def test_oidc_and_introspection_always_allowed(
        self, _name: str, requested: list[str], app_scopes: list[str]
    ) -> None:
        assert scopes_within_ceiling(requested, app_scopes) is True

    def test_wildcard_under_empty_ceiling_gated_by_flag(self) -> None:
        # The one resolution difference between callers: /authorize grandfathers `*`
        # under an empty ceiling, provisioning (default) does not.
        assert scopes_within_ceiling(["*"], [], allow_wildcard_under_empty_ceiling=True) is True
        assert scopes_within_ceiling(["*"], [], allow_wildcard_under_empty_ceiling=False) is False

    @parameterized.expand(
        [
            ("empty_falls_back_to_unprivileged", [], UNPRIVILEGED_SCOPES),
            ("explicit_list_is_exhaustive", ["query:read", "insight:read"], frozenset({"query:read", "insight:read"})),
            (
                "default_sentinel_expands_to_unprivileged_plus_extras",
                ["@default", "llm_gateway:read"],
                UNPRIVILEGED_SCOPES | {"llm_gateway:read"},
            ),
            (
                "sentinel_and_extras_tolerate_whitespace",
                [" @default ", "llm_gateway:read "],
                UNPRIVILEGED_SCOPES | {"llm_gateway:read"},
            ),
        ]
    )
    def test_effective_ceiling(self, _name: str, app_scopes: list[str], expected: frozenset[str]) -> None:
        assert effective_ceiling(app_scopes) == expected


class TestScopesOutsideCeiling(SimpleTestCase):
    @parameterized.expand(
        [
            ("subset_within_ceiling_none_rejected", ["query:read"], ["query:read", "insight:read"], []),
            ("isolates_offender_from_grantable", ["query:read", "insight:write"], ["query:read"], ["insight:write"]),
            ("privileged_rejected_without_ceiling", ["llm_gateway:read"], [], ["llm_gateway:read"]),
            ("wildcard_rejected_under_explicit_ceiling", ["query:read", "*"], ["query:read"], ["*"]),
            ("oidc_never_rejected", ["openid", "insight:write"], ["query:read"], ["insight:write"]),
            (
                "default_sentinel_isolates_unlisted_privileged",
                ["llm_gateway:write", "query:read"],
                ["@default", "llm_gateway:read"],
                ["llm_gateway:write"],
            ),
        ]
    )
    def test_resolution(self, _name: str, requested: list[str], app_scopes: list[str], expected: list[str]) -> None:
        assert scopes_outside_ceiling(requested, app_scopes) == expected

    def test_inverse_of_within_ceiling(self) -> None:
        # The two helpers must never disagree: empty offender list iff within ceiling.
        cases = [
            (["query:read", "insight:write"], ["query:read"]),
            (["query:read"], []),
            (["*"], []),
            (["llm_gateway:write", "query:read"], ["@default", "llm_gateway:read"]),
        ]
        for requested, app_scopes in cases:
            within = scopes_within_ceiling(requested, app_scopes, allow_wildcard_under_empty_ceiling=True)
            outside = scopes_outside_ceiling(requested, app_scopes, allow_wildcard_under_empty_ceiling=True)
            assert within is (outside == [])


class TestNarrowScopesToCeiling(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_ceiling_is_noop", ["query:read", "insight:write"], [], ["query:read", "insight:write"]),
            ("narrows_to_tightened_ceiling", ["query:read", "insight:write"], ["query:read"], ["query:read"]),
            ("no_overlap_returns_none", ["insight:write"], ["query:read"], None),
            ("wildcard_left_untouched", ["*"], ["query:read"], ["*"]),
            (
                "always_allowed_survive_narrowing",
                ["openid", "query:read", "insight:write"],
                ["query:read"],
                ["openid", "query:read"],
            ),
            # OIDC alone keeps the token alive even when every resource scope falls
            # outside the ceiling — mirrors OAuthValidator.get_original_scopes.
            (
                "only_always_allowed_survive_when_resource_scopes_drop",
                ["openid", "insight:write"],
                ["query:read"],
                ["openid"],
            ),
            # `@default` ceiling narrows to the unprivileged default plus listed extras,
            # dropping a hidden scope (`wizard_session:read`) the default doesn't cover.
            (
                "default_sentinel_keeps_unprivileged_and_extras",
                ["query:read", "llm_gateway:read", "wizard_session:read"],
                ["@default", "llm_gateway:read"],
                ["llm_gateway:read", "query:read"],
            ),
        ]
    )
    def test_resolution(
        self, _name: str, requested: list[str], app_scopes: list[str], expected: list[str] | None
    ) -> None:
        assert narrow_scopes_to_ceiling(requested, app_scopes) == expected


class TestFilterToUnprivilegedScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("keeps_unprivileged", ["insight:read", "dashboard:write"], ["insight:read", "dashboard:write"]),
            ("drops_privileged", ["llm_gateway:read", "insight:read"], ["insight:read"]),
            ("drops_unknown_string", ["not_a_real_scope:write", "query:read"], ["query:read"]),
            (
                "dedupes_preserving_order",
                ["insight:read", "query:read", "insight:read"],
                ["insight:read", "query:read"],
            ),
            ("empty_in_empty_out", [], []),
            ("all_dropped_yields_empty", ["llm_gateway:read", "garbage"], []),
            # A self-registering app can't inject the ceiling sentinel to widen itself.
            ("drops_default_sentinel", ["@default", "insight:read"], ["insight:read"]),
        ]
    )
    def test_resolution(self, _name: str, given: list[str], expected: list[str]) -> None:
        assert filter_to_unprivileged_scopes(given) == expected

    def test_non_string_entries_dropped(self) -> None:
        # Callers pass raw partner JSON (CIMD `com.posthog.scopes`), which may hold non-strings.
        assert filter_to_unprivileged_scopes(["insight:read", 123, None, {"x": 1}, "query:read"]) == [
            "insight:read",
            "query:read",
        ]
