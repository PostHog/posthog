import re
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scopes import (
    ALWAYS_ALLOWED_SCOPES,
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION,
    UNPRIVILEGED_SCOPES,
    clamp_scopes_to_ceiling,
    effective_ceiling,
    filter_to_unprivileged_scopes,
    get_oauth_scopes_supported,
    get_scope_descriptions,
    grantable_ceiling,
    narrow_scopes_to_ceiling,
    resolve_ceiling,
    scopes_outside_ceiling,
    scopes_within_ceiling,
)

# Scope rules that are pure functions over constants: no database, no Django fixtures.
# Cases that need a database live in test_scopes.py.


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

    def test_always_allowed_scopes_are_advertised(self) -> None:
        # Every ALWAYS_ALLOWED_SCOPES member is granted on every token, so discovery
        # metadata that omits one under-reports what the token carries. Clients such as
        # ChatGPT compare the scopes they asked for against `scopes_supported` and warn
        # the user that consent was only partly granted.
        advertised = set(get_oauth_scopes_supported())
        for scope in ALWAYS_ALLOWED_SCOPES:
            assert scope in advertised, (
                f"{scope} is granted on every token via ALWAYS_ALLOWED_SCOPES but is missing from "
                "`scopes_supported` in OAuth discovery metadata."
            )


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

    @parameterized.expand(
        [
            ("write_entry_admits_its_read_half", ["insight:write"], ["insight:read"], ["insight:read"]),
            ("read_entry_does_not_admit_write", ["insight:read"], ["insight:write"], []),
            (
                "read_only_downgrade_of_a_whole_write_ceiling",
                ["insight:write", "experiment:write"],
                ["insight:read", "experiment:read"],
                ["experiment:read", "insight:read"],
            ),
        ]
    )
    def test_write_ceiling_entry_admits_read(
        self, _name: str, app_scopes: list[str], requested: list[str], expected: list[str]
    ) -> None:
        assert clamp_scopes_to_ceiling(requested, app_scopes) == expected

    def test_read_halves_do_not_reach_the_literal_ceiling(self) -> None:
        # `create_wizard_oauth_access_token_for_user` and the provisioning account-request
        # path mint `resolve_ceiling`/`effective_ceiling` verbatim as a token. Adding read
        # halves there would hand out scope strings nobody asked for, so the expansion
        # lives in `grantable_ceiling`, which only decides what a request may name.
        assert resolve_ceiling(["insight:write"]) == frozenset({"insight:write"})
        assert effective_ceiling(["insight:write"]) == frozenset({"insight:write"})
        assert grantable_ceiling(["insight:write"]) == frozenset({"insight:write", "insight:read"})

    @parameterized.expand(
        [
            # A token that HELD scopes now outside the ceiling: rejecting is right,
            # because re-authorizing can still grant whatever is inside it.
            ("held_scopes_now_outside_ceiling_rejects", ["experiment:write"], None),
            # A token that never held any: rejecting would loop, since /authorize
            # clamps and hands the same empty grant back on re-authorization.
            ("never_held_any_scope_narrows_to_empty", [], []),
        ]
    )
    def test_nothing_surviving_narrowing_depends_on_whether_there_was_anything(
        self, _name: str, original: list[str], expected: list[str] | None
    ) -> None:
        assert narrow_scopes_to_ceiling(original, ["dashboard:read"]) == expected

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
    def test_resolution(self, _name: str, requested: list[str], app_scopes: list[str], expected: list[str]) -> None:
        assert narrow_scopes_to_ceiling(requested, app_scopes) == expected


class TestClampScopesToCeiling(SimpleTestCase):
    @parameterized.expand(
        [
            ("subset_of_ceiling_passes_through", ["query:read"], ["query:read", "insight:read"], ["query:read"]),
            # The regression this exists for: one ungrantable scope used to fail the whole
            # authorization, so a client asking for a retired or hidden scope alongside valid
            # ones could not connect at all.
            (
                "ungrantable_scope_dropped_not_rejected",
                ["query:read", "insight:write"],
                ["query:read"],
                ["query:read"],
            ),
            ("retired_scope_dropped_under_empty_ceiling", ["query:read", "agents:read"], [], ["query:read"]),
            ("hidden_scope_dropped_under_empty_ceiling", ["query:read", "wizard_session:read"], [], ["query:read"]),
            ("privileged_scope_dropped_under_empty_ceiling", ["query:read", "llm_gateway:read"], [], ["query:read"]),
            # An identity-only grant is a real outcome, not a rejection: /authorize never
            # fails on scope grounds, so the client signs in and 403s on resource calls.
            ("all_resource_scopes_ungrantable_grants_nothing", ["insight:write"], ["query:read"], []),
            ("unknown_scope_alone_grants_nothing", ["agents:read"], [], []),
            ("identity_only_request_is_not_a_rejection", ["openid", "email"], ["query:read"], ["email", "openid"]),
            (
                "always_allowed_survive_alongside_dropped_scopes",
                ["openid", "query:read", "insight:write"],
                ["query:read"],
                ["openid", "query:read"],
            ),
            (
                "wildcard_resolves_to_explicit_ceiling",
                ["*"],
                ["query:read", "insight:read"],
                ["insight:read", "query:read"],
            ),
            (
                "default_sentinel_keeps_unprivileged_and_listed_extra",
                ["query:read", "llm_gateway:read", "llm_gateway:write"],
                ["@default", "llm_gateway:read"],
                ["llm_gateway:read", "query:read"],
            ),
        ]
    )
    def test_resolution(self, _name: str, requested: list[str], app_scopes: list[str], expected: list[str]) -> None:
        assert clamp_scopes_to_ceiling(requested, app_scopes) == expected

    def test_wildcard_under_empty_ceiling_gated_by_flag(self) -> None:
        # Narrowing `*` under an empty ceiling would strip the legacy client's full access,
        # so it is kept verbatim where the caller grandfathers it and dropped where it doesn't.
        assert clamp_scopes_to_ceiling(["*"], [], allow_wildcard_under_empty_ceiling=True) == ["*"]
        assert clamp_scopes_to_ceiling(["*"], [], allow_wildcard_under_empty_ceiling=False) == []

    def test_never_grants_outside_the_ceiling(self) -> None:
        # The ceiling stays the sole authority on what a token may hold: clamping may only
        # ever shrink a request, so any result is a subset of what the old all-or-nothing
        # check would have allowed through.
        cases = [
            (["query:read", "insight:write", "llm_gateway:read"], ["query:read", "insight:read"]),
            (["*"], ["query:read"]),
            (["query:read", "agents:read"], []),
            (["query:read", "llm_gateway:write"], ["@default", "llm_gateway:read"]),
        ]
        for requested, app_scopes in cases:
            clamped = clamp_scopes_to_ceiling(requested, app_scopes, allow_wildcard_under_empty_ceiling=True)
            assert scopes_within_ceiling(clamped, app_scopes, allow_wildcard_under_empty_ceiling=True)


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


class TestProjectSecretAPIKeyScopeParity(SimpleTestCase):
    # The settings scope picker builds its checkboxes from the frontend copy of this list,
    # so a scope added on the backend alone is allowed by the API but has no UI to grant it.
    def test_frontend_list_matches_backend(self) -> None:
        tsx = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "scopes.tsx").read_text()
        match = re.search(
            r"export const PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION = \[(.*?)\] as const",
            tsx,
            re.DOTALL,
        )
        assert match, "Could not find PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION in scopes.tsx"

        frontend_scopes = set(re.findall(r"'([a-z_]+:[a-z]+)'", match.group(1)))
        backend_scopes = {f"{obj}:{action}" for obj, action in PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION}
        assert frontend_scopes == backend_scopes
