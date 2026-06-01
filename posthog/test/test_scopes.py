from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scopes import (
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
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
    def test_signal_scout_internal_is_internal(self) -> None:
        # The scout internal scope must stay in INTERNAL_API_SCOPE_OBJECTS so it is
        # strict-excluded from PAK descriptions, OAuth metadata, and the /authorize
        # allowlist. It is minted server-side only (direct OAuthAccessToken insert).
        assert "signal_scout_internal" in INTERNAL_API_SCOPE_OBJECTS


class TestGetOAuthScopesSupported(SimpleTestCase):
    def test_signal_scout_internal_write_is_not_advertised(self) -> None:
        # Security invariant — the scout sandbox token carries `signal_scout_internal:write`
        # but is minted by direct DB insert (posthog/temporal/oauth.py), never via /authorize.
        # Advertising it in OAuth metadata would let any OAuth client request it via user
        # consent, a durable prompt-injection vector (scratchpad rows are read verbatim into
        # every subsequent run's prompt). It must NOT appear in the advertised scope set.
        assert "signal_scout_internal:write" not in get_oauth_scopes_supported()
        assert "signal_scout_internal:read" not in get_oauth_scopes_supported()

    @parameterized.expand(
        [
            ("user_interview_DO_NOT_USE:read",),
            ("user_interview_DO_NOT_USE:write",),
        ]
    )
    def test_oauth_hidden_scopes_are_not_advertised(self, scope: str) -> None:
        assert scope not in get_oauth_scopes_supported()

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
