from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication, Organization, Team, User
from posthog.temporal.oauth import (
    INTERNAL_SCOPES,
    MCP_READ_SCOPES,
    MCP_WRITE_SCOPES,
    POSTHOG_AI_APP_CLIENT_ID_DEV,
    SCOUT_INTERNAL_SCOPES,
    SCOUT_USER_WRITE_SCOPES,
    create_oauth_access_token_for_user,
    create_wizard_oauth_access_token_for_user,
    has_write_scopes,
    resolve_scopes,
)

_WIZARD_CLIENT_ID = "wizard-test-client-id"


class TestResolveScopes(SimpleTestCase):
    def test_read_only_preset(self) -> None:
        result = resolve_scopes("read_only")
        assert set(result) == set(MCP_READ_SCOPES + INTERNAL_SCOPES)
        assert "action:write" not in result

    def test_read_only_is_default(self) -> None:
        assert resolve_scopes() == resolve_scopes("read_only")

    def test_full_preset(self) -> None:
        result = resolve_scopes("full")
        assert set(result) == set(MCP_READ_SCOPES + MCP_WRITE_SCOPES + INTERNAL_SCOPES)

    def test_signals_scout_preset_adds_scout_internal_write(self) -> None:
        # `signals_scout` = `read_only` content PLUS the scout's own internal write scope
        # PLUS the narrow user-facing write allowlist (`SCOUT_USER_WRITE_SCOPES`). No other
        # user-facing write scopes (e.g. `action:write`) leak in.
        result = resolve_scopes("signals_scout")
        assert set(result) == set(MCP_READ_SCOPES + INTERNAL_SCOPES + SCOUT_INTERNAL_SCOPES + SCOUT_USER_WRITE_SCOPES)
        assert "signal_scout_internal:write" in result
        assert "notebook:write" in result
        assert "action:write" not in result

    def test_scout_internal_write_only_on_signals_scout_preset(self) -> None:
        # Isolation invariant — the scout write scope must NOT leak onto unrelated
        # task tokens. Regular tasks default to `full`; neither `full` nor `read_only`
        # may carry `signal_scout_internal:write` (only the `signals_scout` preset does).
        assert "signal_scout_internal:write" not in resolve_scopes("full")
        assert "signal_scout_internal:write" not in resolve_scopes("read_only")
        assert "signal_scout_internal:write" not in resolve_scopes(["feature_flag:read"])
        assert "signal_scout_internal:write" in resolve_scopes("signals_scout")

    @parameterized.expand([(scope,) for scope in SCOUT_USER_WRITE_SCOPES])
    def test_scout_user_write_allowlist_isolated_from_read_only_tokens(self, scope: str) -> None:
        # The scout's user-facing write allowlist (e.g. `notebook:write`) must reach the
        # `signals_scout` preset but NOT leak onto read-only task tokens. It legitimately
        # appears in `full` (which carries every MCP write scope) — that is expected and is
        # not what this invariant guards.
        assert scope in resolve_scopes("signals_scout")
        assert scope not in resolve_scopes("read_only")
        assert scope not in resolve_scopes(["feature_flag:read"])

    def test_signals_scout_user_write_allowlist_ignores_internal_scopes_flag(self) -> None:
        # `SCOUT_USER_WRITE_SCOPES` are ordinary public scopes, not internal ones, so they
        # are granted to the scout posture independently of `include_internal_scopes`.
        # Dropping internal scopes still strips the scout's own internal write scope.
        result = resolve_scopes("signals_scout", include_internal_scopes=False)
        assert set(result) == set(MCP_READ_SCOPES + SCOUT_USER_WRITE_SCOPES)
        assert "notebook:write" in result
        assert "signal_scout_internal:write" not in result
        for scope in INTERNAL_SCOPES:
            assert scope not in result

    def test_custom_scopes(self) -> None:
        custom = ["feature_flag:read", "feature_flag:write"]
        result = resolve_scopes(custom)
        assert set(result) == set(custom + INTERNAL_SCOPES)

    def test_internal_scopes_always_included(self) -> None:
        for scope in INTERNAL_SCOPES:
            assert scope in resolve_scopes("read_only")
            assert scope in resolve_scopes("full")
            assert scope in resolve_scopes(["feature_flag:read"])

    def test_include_internal_scopes_false_drops_internal_scopes(self) -> None:
        custom = ["clickhouse_test_cluster_perf:read"]
        result = resolve_scopes(custom, include_internal_scopes=False)
        assert result == custom
        for scope in INTERNAL_SCOPES:
            assert scope not in result

    def test_include_internal_scopes_false_for_read_only_preset(self) -> None:
        result = resolve_scopes("read_only", include_internal_scopes=False)
        assert set(result) == set(MCP_READ_SCOPES)
        for scope in INTERNAL_SCOPES:
            assert scope not in result

    def test_deduplicates_overlapping_scopes(self) -> None:
        custom = ["feature_flag:read", "feature_flag:read", "task:write", "insight:read"]
        result = resolve_scopes(custom)
        assert len(result) == len(set(result)), f"expected no duplicates, got {result}"
        # task:write is in INTERNAL_SCOPES; appears once despite being in both inputs
        assert result.count("task:write") == 1
        assert result.count("feature_flag:read") == 1
        # First-seen order is preserved
        assert result.index("feature_flag:read") < result.index("task:write")

    def test_internal_scope_objects_disjoint_from_mcp_scope_lists(self) -> None:
        from posthog.scopes import INTERNAL_API_SCOPE_OBJECTS

        mcp_scope_objects: set[str] = {scope.split(":", 1)[0] for scope in [*MCP_READ_SCOPES, *MCP_WRITE_SCOPES]}
        internal: set[str] = set(INTERNAL_API_SCOPE_OBJECTS)
        overlap = internal & mcp_scope_objects
        assert overlap == set(), (
            f"{overlap} are in INTERNAL_API_SCOPE_OBJECTS and also in MCP_READ_SCOPES / MCP_WRITE_SCOPES; "
            "a `read_only` MCP token would silently grant them."
        )


class TestHasWriteScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_only_preset", "read_only", False),
            ("full_preset", "full", True),
            ("signals_scout_preset", "signals_scout", True),
            ("custom_with_mcp_write", ["feature_flag:read", "feature_flag:write"], True),
            ("custom_read_only", ["feature_flag:read", "insight:read"], False),
            ("custom_with_non_mcp_write", ["task:write"], False),
            ("empty_custom", [], False),
        ]
    )
    def test_has_write_scopes(self, _name: str, scopes, expected: bool) -> None:
        assert has_write_scopes(scopes) == expected


class TestCreateOAuthAccessTokenForUser(TestCase):
    def _create_oauth_app(self, client_id: str, name: str) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id=client_id,
            name=name,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8237/callback",
            algorithm="RS256",
        )

    def _create_user_and_team(self) -> tuple[User, Team]:
        organization = Organization.objects.create(name="OAuth test org")
        team = Team.objects.create(organization=organization, name="OAuth test team")
        user = User.objects.create(email="oauth-test@example.com")
        return user, team

    @override_settings(CLOUD_DEPLOYMENT="DEV")
    def test_posthog_ai_application_uses_dev_app(self) -> None:
        app = self._create_oauth_app(POSTHOG_AI_APP_CLIENT_ID_DEV, "PostHog AI Dev App")
        user, team = self._create_user_and_team()

        token = create_oauth_access_token_for_user(user, team.id, application="posthog_ai")

        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.application_id == app.id
        assert access_token.scoped_teams == [team.id]

    @override_settings(CLOUD_DEPLOYMENT="DEV")
    def test_posthog_ai_application_requires_existing_app(self) -> None:
        user, team = self._create_user_and_team()

        with self.assertRaisesRegex(RuntimeError, "PostHog AI app not found"):
            create_oauth_access_token_for_user(user, team.id, application="posthog_ai")


class TestCreateWizardOAuthAccessTokenForUser(TestCase):
    def _create_wizard_app(self, scopes: list[str]) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id=_WIZARD_CLIENT_ID,
            name="PostHog Wizard Test App",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8237/callback",
            algorithm="RS256",
            scopes=scopes,
        )

    def _create_user_and_team(self) -> tuple[User, Team]:
        organization = Organization.objects.create(name="Wizard OAuth test org")
        team = Team.objects.create(organization=organization, name="Wizard OAuth test team")
        user = User.objects.create(email="wizard-oauth-test@example.com")
        return user, team

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID=_WIZARD_CLIENT_ID)
    def test_mints_token_under_wizard_app_with_its_scopes(self) -> None:
        # The token must be minted under the wizard's own app (so the gateway authorizes it like a normal wizard run)
        # separate from the agent's sandbox token.
        scopes = ["project:read", "insight:write", "llm_gateway:read"]
        app = self._create_wizard_app(scopes=scopes)
        user, team = self._create_user_and_team()

        token = create_wizard_oauth_access_token_for_user(user, team.id)

        assert token is not None
        assert token.startswith("pha_")

        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.application_id == app.id
        assert access_token.scoped_teams == [team.id]
        assert set(access_token.scope.split()) == set(scopes)

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID=_WIZARD_CLIENT_ID)
    def test_requires_existing_app(self) -> None:
        user, team = self._create_user_and_team()

        with self.assertRaisesRegex(RuntimeError, "Wizard app not found"):
            create_wizard_oauth_access_token_for_user(user, team.id)
