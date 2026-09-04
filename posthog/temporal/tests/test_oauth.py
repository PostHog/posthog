import json
from pathlib import Path
from typing import cast
from uuid import uuid4

from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication, Organization, Team, User
from posthog.scopes import MCP_BUILT_IN_AGENT_SCOPE
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    INTERNAL_SCOPES,
    MCP_READ_SCOPES,
    MCP_WRITE_SCOPES,
    POSTHOG_AI_APP_CLIENT_ID_DEV,
    RESEARCH_WITHHELD_SCOPES,
    SCOUT_GRANTABLE_WRITE_SCOPES,
    SCOUT_INTERNAL_SCOPES,
    SCOUT_SCOPE_PRESETS,
    SCOUT_USER_WRITE_SCOPES,
    SCRATCHPAD_INTERNAL_SCOPES,
    McpScopePreset,
    ScoutScopePosture,
    ScoutScopePreset,
    create_oauth_access_token_for_user,
    create_wizard_oauth_access_token_for_user,
    has_write_scopes,
    resolve_scopes,
    scout_scope_posture,
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
        # The two pipeline postures exist precisely so they can write memory WITHOUT it,
        # so they must not carry it either — nor the report channel's scope.
        without_scout_scopes: tuple[McpScopePreset, ...] = (
            "full",
            "read_only",
            "signals_research",
            "signals_implementation",
        )
        for preset in without_scout_scopes:
            assert "signal_scout_internal:write" not in resolve_scopes(preset)
            assert "signal_scout_report:write" not in resolve_scopes(preset)
        assert "signal_scout_internal:write" not in resolve_scopes(["feature_flag:read"])
        assert "signal_scout_internal:write" in resolve_scopes("signals_scout")

    def test_signals_research_preset_is_reads_plus_the_scratchpad(self) -> None:
        # The research stage is read-only by design, and stays that way apart from memory.
        # `task:write` is withheld because turning the MCP read-only header off (see
        # `has_write_scopes`) would otherwise hand it every task-write tool, including
        # setting a report's state.
        result = resolve_scopes("signals_research")
        expected = set(MCP_READ_SCOPES + INTERNAL_SCOPES + SCRATCHPAD_INTERNAL_SCOPES) - RESEARCH_WITHHELD_SCOPES
        assert set(result) == expected
        assert "signal_scratchpad_internal:write" in result
        assert "task:write" not in result
        assert "action:write" not in result

    def test_signals_implementation_preset_is_full_plus_the_scratchpad(self) -> None:
        result = resolve_scopes("signals_implementation")
        assert set(result) == set(MCP_READ_SCOPES + MCP_WRITE_SCOPES + INTERNAL_SCOPES + SCRATCHPAD_INTERNAL_SCOPES)

    def test_scratchpad_write_reaches_scouts_and_the_pipeline_only(self) -> None:
        # Splitting the scope out of `signal_scout_internal` must not cost scouts their
        # remember/forget tools, and must not hand them to unrelated task tokens.
        carriers: tuple[McpScopePreset, ...] = (
            "signals_scout",
            "signals_scout_reports",
            "signals_research",
            "signals_implementation",
        )
        for preset in carriers:
            assert "signal_scratchpad_internal:write" in resolve_scopes(preset)
        others: tuple[McpScopePreset, ...] = ("read_only", "full")
        for preset in others:
            assert "signal_scratchpad_internal:write" not in resolve_scopes(preset)
        assert "signal_scratchpad_internal:write" not in resolve_scopes(["feature_flag:read"])

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

    def test_scout_posture_adds_only_the_granted_write_scopes(self) -> None:
        # The feature itself: a grant reaches the token, and only the granted scope does.
        # A posture that resolved to the whole allowlist would hand every scout that holds one
        # grant the other three.
        result = resolve_scopes(scout_scope_posture("signals_scout", ["dashboard:write"]))
        assert set(result) == set(resolve_scopes("signals_scout")) | {"dashboard:write"}
        assert "insight:write" not in result

    @parameterized.expand([(preset,) for preset in SCOUT_SCOPE_PRESETS])
    def test_scout_posture_without_a_grant_matches_the_plain_preset(self, preset: ScoutScopePreset) -> None:
        # The fixed posture has to survive the new branch whole. A composition that rebuilt the
        # preset by hand would drop `signal_scout_internal:write`, the scratchpad scopes, or the
        # report channel, and the scout would lose the tools it exists to call.
        assert set(resolve_scopes(scout_scope_posture(preset))) == set(resolve_scopes(preset))

    @parameterized.expand(
        [
            ("write_scope_outside_the_allowlist", "feature_flag:write"),
            # The report channel is granted by the preset a scout's skill opted into, never by
            # the per-scout field. A baseline scout must not reach emit_report through a grant.
            ("internal_scope", "signal_scout_report:write"),
            ("scope_that_does_not_exist", "not_a_real_object:write"),
        ]
    )
    def test_scout_posture_drops_scopes_outside_the_grantable_allowlist(self, _name: str, ungrantable: str) -> None:
        # Mint-time intersection. A config row written before the allowlist shrank, or edited
        # outside the API, reaches this function unchanged, so this is the gate that binds.
        posture: ScoutScopePosture = {
            "preset": "signals_scout",
            "extra_write_scopes": [ungrantable, "dashboard:write"],
        }
        result = resolve_scopes(posture)
        assert set(result) == set(resolve_scopes("signals_scout")) | {"dashboard:write"}

    @parameterized.expand(
        [
            # A non-scout preset carrying extras is the invariant this guards: a read-only task
            # token must never carry a user-facing write scope, whatever the posture claims.
            (
                "non_scout_preset",
                cast(ScoutScopePosture, {"preset": "full", "extra_write_scopes": ["dashboard:write"]}),
            ),
            ("missing_preset", cast(ScoutScopePosture, {"extra_write_scopes": ["dashboard:write"]})),
        ]
    )
    def test_malformed_scout_posture_resolves_to_read_only(self, _name: str, posture: ScoutScopePosture) -> None:
        result = resolve_scopes(posture)
        assert set(result) == set(resolve_scopes("read_only"))
        assert not has_write_scopes(posture)

    @parameterized.expand(
        [
            ("grant_is_not_a_list", "dashboard:write", set()),
            # An entry JSON allows but a set cannot hold. Building the set before filtering
            # raises TypeError, which aborts the run instead of degrading to the ungranted
            # posture the way a malformed grant is meant to.
            ("entry_is_an_object", [{"scope": "dashboard:write"}], set()),
            ("entry_is_a_list", [["insight:write"], "dashboard:write"], {"dashboard:write"}),
        ]
    )
    def test_scout_posture_tolerates_malformed_grant_entries(
        self, _name: str, raw: object, expected_extra: set[str]
    ) -> None:
        posture = cast(ScoutScopePosture, {"preset": "signals_scout", "extra_write_scopes": raw})
        assert set(resolve_scopes(posture)) == set(resolve_scopes("signals_scout")) | expected_extra

    def test_scout_scope_posture_drops_ungrantable_scopes(self) -> None:
        # The build-time gate. What this returns is both the mint request and the record of
        # what a run was dispatched with, so a builder that passed its input through would widen
        # the token and describe it wrongly at the same time.
        assert scout_scope_posture("signals_scout", ["dashboard:write", "feature_flag:write"]) == {
            "preset": "signals_scout",
            "extra_write_scopes": ["dashboard:write"],
        }

    def test_scout_posture_survives_a_json_round_trip(self) -> None:
        # The posture is stored on a task's `pending_dispatch` JSON column and travels through
        # Temporal payloads, so it has to resolve the same after `json.dumps` / `json.loads`.
        posture = scout_scope_posture("signals_scout_reports", ["insight:write", "dashboard:write"])
        assert resolve_scopes(json.loads(json.dumps(posture))) == resolve_scopes(posture)

    def test_grantable_write_scopes_are_mcp_write_scopes(self) -> None:
        # A typo or an internal scope in the allowlist would offer a person a switch that grants
        # nothing, because the MCP server gates its tools on scopes it advertises.
        assert SCOUT_GRANTABLE_WRITE_SCOPES <= set(MCP_WRITE_SCOPES)

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
            # Both pipeline postures need read-only mode off, or the MCP server strips the
            # scratchpad tools the postures exist to grant.
            ("signals_research_preset", "signals_research", True),
            ("signals_implementation_preset", "signals_implementation", True),
            # Read-only mode has to stay off for a scout posture, or the MCP server strips the
            # scout's own tools whether or not the scout holds a grant.
            ("scout_posture_with_a_grant", {"preset": "signals_scout", "extra_write_scopes": ["alert:write"]}, True),
            ("scout_posture_without_a_grant", {"preset": "signals_scout_reports", "extra_write_scopes": []}, True),
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
    def test_task_binding_is_persisted_only_when_supplied(self) -> None:
        self._create_oauth_app(ARRAY_APP_CLIENT_ID_DEV, "Array Dev App")
        user, team = self._create_user_and_team()
        task_id = uuid4()

        bound = create_oauth_access_token_for_user(user, team.id, sandbox_task_id=task_id)
        unbound = create_oauth_access_token_for_user(user, team.id)

        assert OAuthAccessToken.objects.get(token=bound).sandbox_task_id == task_id
        assert OAuthAccessToken.objects.get(token=unbound).sandbox_task_id is None

    @override_settings(CLOUD_DEPLOYMENT="DEV")
    def test_posthog_ai_application_requires_existing_app(self) -> None:
        user, team = self._create_user_and_team()

        with self.assertRaisesRegex(RuntimeError, "PostHog AI app not found"):
            create_oauth_access_token_for_user(user, team.id, application="posthog_ai")

    @override_settings(CLOUD_DEPLOYMENT="DEV")
    def test_built_in_agent_scope_is_added_without_narrowing_scopes(self) -> None:
        self._create_oauth_app(ARRAY_APP_CLIENT_ID_DEV, "Array Dev App")
        user, team = self._create_user_and_team()

        token = create_oauth_access_token_for_user(
            user,
            team.id,
            include_mcp_builtin_agent_scope=True,
        )

        scopes = set(OAuthAccessToken.objects.get(token=token).scope.split())
        assert MCP_BUILT_IN_AGENT_SCOPE in scopes
        # The marker is provenance only: built-in agents keep the task tools.
        assert "task:read" in scopes
        assert "task:write" in scopes


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


class TestSignalsResearchToolset(SimpleTestCase):
    """What the MCP server actually serves a `signals_research` token.

    The scope list alone doesn't answer this. Read-only mode is a tool-annotation filter, and the
    posture turns it off so the scratchpad tools survive — so the write surface it opens is
    whatever the resolved scopes let through, which is worth pinning rather than reasoning about.
    Both sides read the same generated catalog the MCP server ships, so this can't drift into
    testing a copy of it.
    """

    _CATALOG = Path(__file__).parents[3] / "services" / "mcp" / "schema" / "generated-tool-definitions.json"

    def test_opens_the_scratchpad_writes_and_nothing_else(self) -> None:
        granted = set(resolve_scopes("signals_research"))
        definitions: dict[str, dict] = json.loads(self._CATALOG.read_text())

        reachable_writes = {
            name
            for name, definition in definitions.items()
            for required in [definition.get("required_scopes") or []]
            if any(scope.endswith(":write") for scope in required) and set(required) <= granted
        }

        # The deprecated `signals-scout-*` aliases forward to the same endpoints, so they move
        # with their canonical names.
        assert reachable_writes == {
            "scout-scratchpad-remember",
            "scout-scratchpad-forget",
            "signals-scout-scratchpad-remember",
            "signals-scout-scratchpad-forget",
        }
