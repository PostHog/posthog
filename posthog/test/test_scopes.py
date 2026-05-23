from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scopes import (
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS,
    downgrade_scopes_to_read_only,
    get_oauth_scopes_supported,
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


class TestScopeBucketInvariants(SimpleTestCase):
    def test_pak_hidden_oauth_grantable_is_subset_of_internal(self) -> None:
        # The carve-out only relaxes the OAuth filter for objects that are ALREADY
        # in INTERNAL_API_SCOPE_OBJECTS. Anything outside that set is already
        # OAuth-grantable by default and doesn't belong here.
        assert PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS <= INTERNAL_API_SCOPE_OBJECTS, (
            f"{PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS - INTERNAL_API_SCOPE_OBJECTS} "
            "are in PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS but not in INTERNAL_API_SCOPE_OBJECTS. "
            "The carve-out only makes sense for objects the OAuth filter would otherwise exclude."
        )

    def test_pak_hidden_oauth_grantable_disjoint_from_oauth_hidden(self) -> None:
        # The two hidden buckets are conceptual opposites — `OAUTH_HIDDEN` is
        # PAK-grantable / OAuth-not-discoverable, `PAK_HIDDEN_OAUTH_GRANTABLE`
        # is the inverse. An object in both would be unreachable everywhere.
        overlap = PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS & OAUTH_HIDDEN_SCOPE_OBJECTS
        assert overlap == set(), (
            f"{overlap} appear in both PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS and OAUTH_HIDDEN_SCOPE_OBJECTS — "
            "an object in both buckets is reachable from neither PAK nor OAuth, which is almost certainly a bug."
        )


class TestGetOAuthScopesSupported(SimpleTestCase):
    def test_signal_scout_internal_write_is_advertised(self) -> None:
        # Regression — without this entry the Signals scout sandbox token is
        # minted with `signal_scout_internal:write` but the MCP server filters
        # it out at session init, leaving the scout unable to call
        # `signals-scout-emit-signal` / `-scratchpad-remember` / `-scratchpad-forget`.
        assert "signal_scout_internal:write" in get_oauth_scopes_supported()

    @parameterized.expand(
        [
            ("user_interview_DO_NOT_USE:read",),
            ("user_interview_DO_NOT_USE:write",),
        ]
    )
    def test_oauth_hidden_scopes_are_not_advertised(self, scope: str) -> None:
        assert scope not in get_oauth_scopes_supported()

    def test_internal_scopes_outside_pak_hidden_carveout_are_not_advertised(self) -> None:
        excluded_objects = INTERNAL_API_SCOPE_OBJECTS - PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS
        advertised = set(get_oauth_scopes_supported())
        for obj in excluded_objects:
            for action in ("read", "write"):
                assert f"{obj}:{action}" not in advertised, (
                    f"{obj}:{action} is in INTERNAL_API_SCOPE_OBJECTS and NOT in PAK_HIDDEN_OAUTH_GRANTABLE_SCOPE_OBJECTS, "
                    "but is being advertised in OAuth metadata — internals should stay hidden by default."
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
    def test_pak_hidden_oauth_grantable_scopes_are_not_pak_descriptions(self, scope: str) -> None:
        # Critical security invariant — the carve-out relaxes ONLY the OAuth
        # filter. PAK validation reads from `get_scope_descriptions()` and must
        # continue to reject `signal_scout_internal` (it's a prompt-injection
        # vector if user-grantable: scratchpad rows are read verbatim into every
        # subsequent scout run's prompt).
        assert scope not in get_scope_descriptions()

    def test_all_non_internal_objects_get_pak_descriptions(self) -> None:
        descriptions = get_scope_descriptions()
        for obj in API_SCOPE_OBJECTS:
            if obj in INTERNAL_API_SCOPE_OBJECTS:
                continue
            for action in ("read", "write"):
                assert f"{obj}:{action}" in descriptions
