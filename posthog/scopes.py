from collections.abc import Iterable
from typing import Literal, get_args

## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes

# WARNING: Make sure to keep in sync with the frontend!
# - frontend/src/lib/scopes.tsx
# - frontend/src/types.ts (`export type APIScopeObject`)
#
# The MCP `OAUTH_SCOPES_SUPPORTED` list at
# `services/mcp/src/lib/oauth-scopes.generated.ts` is generated from
# `get_scope_descriptions()` below via `bin/build-mcp-oauth-scopes.py`. Run
# `hogli build:openapi` to regenerate after editing this file.
APIScopeObject = Literal[
    "action",
    "access_control",
    "account",
    "activity_log",
    "agents",
    "agent_approvals",
    "alert",
    "annotation",
    "approvals",
    "batch_export",
    "batch_import",
    "business_knowledge",
    "clickhouse_test_cluster_perf",
    "cohort",
    "comment",
    "conversation",
    "customer_analytics",
    "customer_journey",
    "customer_profile_config",
    "dashboard",
    "event_filter",
    "dashboard_template",
    "dataset",
    "early_access_feature",
    "endpoint",
    "engineering_analytics",
    "error_tracking",
    "evaluation",
    "element",
    "event_definition",
    "experiment",
    "experiment_holdout",
    "experiment_saved_metric",
    "export",
    "external_data_schema",
    "external_data_source",
    "feature_flag",
    "file_system",
    "file_system_shortcut",
    "group",
    "health_issue",
    "heatmap",
    "hog_flow",
    "hog_function",
    "ingestion_warning",
    "insight",
    "insight_variable",
    "integration",
    "legal_document",
    "link",
    "live_debugger",
    "llm_analytics",
    "llm_gateway",
    "llm_prompt",
    "llm_provider_key",
    "llm_skill",
    "logs",
    "marketing_analytics",
    "mcp_analytics",
    "metrics",
    "notebook",
    "organization",
    "organization_integration",
    "organization_member",
    "person",
    "plugin",
    "product_enablement",
    "product_tour",
    "project",
    "property_definition",
    "query",  # Covers query and events endpoints
    "query_performance",
    "replay_scanner",
    "revenue_analytics",
    "session_recording",
    "session_recording_playlist",
    "sharing_configuration",
    "signal_scout",
    "signal_scout_internal",
    "signal_scout_report",
    "streamlit_app",
    "subscription",
    "survey",
    "tagger",
    "ticket",
    "task",
    "tracing",
    "field_note",
    "uploaded_media",
    "usage_metric",
    "user",
    "user_interview",  # Alpha product — access gated by feature flag at the MCP/API layer rather than by hiding the scope.
    "vision_action",
    "visual_review",
    "warehouse_objects",
    "warehouse_table",
    "warehouse_view",
    "web_analytics",
    "webhook",
    "wizard_session",
]

APIScopeActions = Literal[
    "read",
    "write",
]

APIScopeObjectOrNotSupported = Literal[
    APIScopeObject,
    "INTERNAL",
]

API_SCOPE_OBJECTS: tuple[APIScopeObject, ...] = get_args(APIScopeObject)
API_SCOPE_ACTIONS: tuple[APIScopeActions, ...] = get_args(APIScopeActions)

# Scope objects minted programmatically only — never via the OAuth consent flow,
# the personal-API-key UI, the CLI authorize page, or RBAC. Filtered out of
# `get_scope_descriptions()` and rejected by every user-facing scope validator.
INTERNAL_API_SCOPE_OBJECTS: frozenset[APIScopeObject] = frozenset(
    {
        "clickhouse_test_cluster_perf",
        # Sandbox-only writes for the headless Signals agent (memory create/delete,
        # finding emit). Read access for the same surface lives on the public
        # `signal_scout` object so user-grantable PAKs can still inspect runs/memory.
        "signal_scout_internal",
        # Sandbox-only write for the scout report channel (emit_report / edit_report).
        # Split out from `signal_scout_internal` so it can be granted ONLY to scouts that
        # opted into the report tools (via the `signals_scout_reports` posture) — every
        # other scout's token lacks it, so the MCP server strips those tools entirely.
        "signal_scout_report",
    }
)

# Scope objects available via personal API keys but never advertised through
# OAuth metadata. Used where a user can manually paste the scope into a PAT but
# we don't want OAuth-based clients (the consent screen, MCP, third-party apps)
# to discover it — alpha / not-yet-public products, or staff-only debug endpoints
# automation reaches with a PAT (e.g. `query_performance`, also gated by `is_staff`).
OAUTH_HIDDEN_SCOPE_OBJECTS: frozenset[APIScopeObject] = frozenset({"wizard_session", "query_performance"})

# llm_gateway:read is omitted on purpose: it's alpha/privileged and granted only behind the
# ai-gateway flag in ProjectSecretAPIKeySerializer, not unconditionally like the entries here.
PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[APIScopeObject, APIScopeActions]] = [
    ("endpoint", "read"),
    # SDK local evaluation and remote config. The Rust feature-flags service already
    # validates feature_flag:read PSAKs on the flag-definitions path; this makes them creatable.
    ("feature_flag", "read"),
]

# Server-side scope assignment string-set constants (see RFC: server-side scope
# assignment for OAuthApplications).
#
# Naming convention in this module: `*_SCOPE_OBJECTS` (frozenset[APIScopeObject])
# and `*_SCOPE_ACTIONS` hold scope-OBJECT sets; bare `*_SCOPES` (frozenset[str])
# hold scope-STRING (`obj:action`) sets. The object sets above
# (INTERNAL_API_SCOPE_OBJECTS, OAUTH_HIDDEN_SCOPE_OBJECTS) remain canonical for
# object-level checks; the string sets below are the surface used by
# `OAuthApplication.scopes` and `UNPRIVILEGED_SCOPES` set arithmetic.

# Every public `obj:action` scope string. Matches `get_scope_descriptions()`
# keys; excludes INTERNAL scopes (programmatic-only, never user-facing).
ALL_SCOPES: frozenset[str] = frozenset(
    f"{obj}:{action}"
    for obj in API_SCOPE_OBJECTS
    if obj not in INTERNAL_API_SCOPE_OBJECTS
    for action in API_SCOPE_ACTIONS
)

# Privileged scopes only land on `OAuthApplication.scopes` via an admin-driven
# path (Django admin, the Stripe HMAC seed list, first-party data migrations).
# Filtered out of partner-facing self-serve registration (CIMD, DCR per
# RFC 7591), so a partner cannot programmatically grant themselves
# `llm_gateway:read`.
PRIVILEGED_SCOPES: frozenset[str] = frozenset({"llm_gateway:read", "llm_gateway:write"})

# String form of `OAUTH_HIDDEN_SCOPE_OBJECTS`. PAT-grantable but never
# advertised via OAuth metadata; excluded from `UNPRIVILEGED_SCOPES` so an
# alpha scope never reaches the broad default. Intersected with `ALL_SCOPES`
# so a future hidden object whose action set narrows doesn't carry a phantom
# string into the set.
OAUTH_HIDDEN_SCOPES: frozenset[str] = (
    frozenset(f"{obj}:{action}" for obj in OAUTH_HIDDEN_SCOPE_OBJECTS for action in API_SCOPE_ACTIONS) & ALL_SCOPES
)

# Everything safe to grant a generic OAuth client. The broad default for an
# `OAuthApplication` with empty `scopes`: empty resolves to this set at
# `/authorize` time. OIDC scopes (openid/profile/email) are NOT in this set —
# they live in `OIDC_SCOPES` below and are accepted at `/authorize`
# independently of `application.scopes`.
UNPRIVILEGED_SCOPES: frozenset[str] = ALL_SCOPES - PRIVILEGED_SCOPES - OAUTH_HIDDEN_SCOPES


def get_scope_descriptions() -> dict[str, str]:
    return {
        f"{obj}:{action}": f"{action.capitalize()} access to {obj}"
        for obj in API_SCOPE_OBJECTS
        if obj not in INTERNAL_API_SCOPE_OBJECTS
        for action in API_SCOPE_ACTIONS
    }


def downgrade_scopes_to_read_only(scope_str: str) -> str:
    """Strip write access from a space-separated OAuth scope string.

    - `<object>:write` becomes `<object>:read`.
    - `*` is the full-access wildcard (see `posthog/permissions.py` — `if "*" in key_scopes`
      short-circuits the scope check, granting read+write). Pass-through would defeat the
      downgrade, so `*` is expanded to every public `*:read` scope.
    - Existing `<object>:read` scopes and OIDC scopes (`openid`, `profile`, `email`) pass through.

    Returns a deduped, space-separated string preserving first-seen order.
    """
    if not scope_str:
        return scope_str
    all_public_read_scopes = [
        f"{obj}:read"
        for obj in API_SCOPE_OBJECTS
        if obj not in INTERNAL_API_SCOPE_OBJECTS and obj not in OAUTH_HIDDEN_SCOPE_OBJECTS
    ]
    expanded: list[str] = []
    for raw in scope_str.split():
        if raw == "*":
            expanded.extend(all_public_read_scopes)
        elif raw.endswith(":write"):
            expanded.append(raw[: -len(":write")] + ":read")
        else:
            expanded.append(raw)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in expanded:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return " ".join(deduped)


# OIDC scopes published in OAuth server metadata alongside the resource scopes.
# These match what django-oauth-toolkit's OIDC layer accepts at the /authorize
# endpoint. Duplicating the list as plain tuple (rather than importing from
# oauth_toolkit) keeps `posthog.scopes` importable without Django setup, which
# the MCP codegen relies on (see `bin/build-mcp-oauth-scopes.py`).
OIDC_SCOPES: tuple[str, ...] = ("openid", "profile", "email")


# OIDC + introspection are accepted independently of an app's scope ceiling:
# they are identity / token-management scopes, not resource permissions. Mirrors
# `OAuthValidator._ALWAYS_ALLOWED_SCOPES` in `posthog/api/oauth/views.py`.
ALWAYS_ALLOWED_SCOPES: frozenset[str] = frozenset(OIDC_SCOPES) | {"introspection"}


def filter_to_unprivileged_scopes(scopes: Iterable[object]) -> list[str]:
    """Keep only self-serve-grantable scopes from a declared list, deduped, order preserved.

    The single allow-list for scopes a self-registering client declares, covering both DCR
    (the RFC 7591 `scope` string, split before it gets here) and CIMD (`com.posthog.scopes`).
    `UNPRIVILEGED_SCOPES` drops privileged (`llm_gateway:*`), internal, hidden, and unknown
    strings: none may reach a per-app ceiling, since `/authorize` would otherwise grant them
    on a user-consented token. Non-string entries are dropped too, so raw partner JSON is safe
    to pass straight in.
    """
    seen: set[str] = set()
    result: list[str] = []
    for token in scopes:
        if not isinstance(token, str) or token not in UNPRIVILEGED_SCOPES or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


# Sentinel element in `OAuthApplication.scopes` meaning "the `UNPRIVILEGED_SCOPES`
# default *plus* the other listed scopes" — lets an app ride the broad default and add
# a few explicit (e.g. privileged) extras without enumerating the whole set, and keeps
# auto-tracking unprivileged scopes added later. Starts with `@` so it can never collide
# with a real `obj:action` scope. Not grantable itself: it's stripped from the resolved
# ceiling, and `filter_to_unprivileged_scopes` drops it so a self-registering app can't
# inject it to widen its own ceiling.
DEFAULT_CEILING_SENTINEL = "@default"


def resolve_ceiling(app_scopes: Iterable[str]) -> frozenset[str] | None:
    """An app's explicit scope ceiling, or `None` when it has none (empty `scopes`,
    which falls back to the `UNPRIVILEGED_SCOPES` default). A `@default` sentinel
    expands to `UNPRIVILEGED_SCOPES` unioned with the other listed scopes; without it,
    a non-empty ceiling stays an exhaustive allow-list. Entries are stripped so a
    fat-fingered `" @default"` still resolves (real scopes never have whitespace)."""
    app = {s.strip() for s in (app_scopes or [])}
    app.discard("")
    if not app:
        return None
    if DEFAULT_CEILING_SENTINEL in app:
        return frozenset(UNPRIVILEGED_SCOPES | (app - {DEFAULT_CEILING_SENTINEL}))
    return frozenset(app)


def effective_ceiling(app_scopes: Iterable[str]) -> frozenset[str]:
    """The scope set a request resolves against: the explicit `app_scopes` ceiling,
    or the broad `UNPRIVILEGED_SCOPES` default when the app has none."""
    ceiling = resolve_ceiling(app_scopes)
    return ceiling if ceiling is not None else UNPRIVILEGED_SCOPES


def scopes_within_ceiling(
    requested: Iterable[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> bool:
    """Whether every requested scope is grantable under an app's scope ceiling.

    The single source of truth for ceiling resolution: `/authorize`
    (`OAuthValidator.validate_scopes`) and the hand-rolled agentic-provisioning
    mint paths both call this so they enforce identical rules.

    - OIDC + introspection (`ALWAYS_ALLOWED_SCOPES`) are always granted.
    - An explicit `app_scopes` ceiling is an exhaustive allow-list: anything
      outside it is rejected, including `*`.
    - A `@default` sentinel in `app_scopes` resolves to `UNPRIVILEGED_SCOPES` plus
      the other listed scopes (see `resolve_ceiling`).
    - An empty `app_scopes` falls back to the broad `UNPRIVILEGED_SCOPES` default.

    `allow_wildcard_under_empty_ceiling` is the only resolution difference between
    the callers: `/authorize` passes `True` to grandfather legacy `*` clients (the
    PostHog Code CLI) until wildcard retirement; provisioning leaves it `False`
    (the default) since it never granted wildcard, so an unseeded ceiling must not
    silently become one.
    """
    ceiling = resolve_ceiling(app_scopes)
    to_check = set(requested) - ALWAYS_ALLOWED_SCOPES
    if not to_check:
        return True
    if ceiling is not None:
        return "*" not in to_check and to_check.issubset(ceiling)
    allowed = UNPRIVILEGED_SCOPES | {"*"} if allow_wildcard_under_empty_ceiling else UNPRIVILEGED_SCOPES
    return to_check.issubset(allowed)


def scopes_outside_ceiling(
    requested: Iterable[str],
    app_scopes: Iterable[str],
    *,
    allow_wildcard_under_empty_ceiling: bool = False,
) -> list[str]:
    """The requested scopes that fall outside an app's ceiling — the inverse of
    `scopes_within_ceiling`, naming *which* scopes triggered an `invalid_scope`
    rejection rather than just whether one did. For instrumentation only; the
    resolution rules mirror `scopes_within_ceiling` exactly so the two never drift.

    Returns a sorted list, empty when every requested scope is grantable.
    """
    ceiling = resolve_ceiling(app_scopes)
    to_check = set(requested) - ALWAYS_ALLOWED_SCOPES
    if not to_check:
        return []
    if ceiling is not None:
        # `*` is never grantable under an explicit ceiling, even if listed.
        return sorted(s for s in to_check if s == "*" or s not in ceiling)
    allowed = UNPRIVILEGED_SCOPES | {"*"} if allow_wildcard_under_empty_ceiling else UNPRIVILEGED_SCOPES
    return sorted(to_check - allowed)


def narrow_scopes_to_ceiling(original: Iterable[str], app_scopes: Iterable[str]) -> list[str] | None:
    """Cap previously-granted scopes at an app's current ceiling (refresh-time).

    Mirrors `OAuthValidator.get_original_scopes` so hand-rolled refresh flows
    drop scopes that were valid when issued but fall outside a since-tightened
    ceiling, rather than refreshing the broader set forever.

    - Empty `app_scopes` (no cap) is a no-op: returns `original` as a list.
    - A `*` token is left untouched (narrowing it would strip all resource
      access; `*` retirement is handled separately).
    - Otherwise returns the sorted intersection with the ceiling plus any
      always-allowed scopes, or `None` when that intersection is empty (the
      caller should reject with `invalid_grant` and force re-authorization).
    """
    original_list = list(original)
    ceiling = resolve_ceiling(app_scopes)
    if ceiling is None:
        return original_list

    original_set = set(original_list)
    if "*" in original_set:
        return original_list

    narrowed = (original_set & ceiling) | (original_set & ALWAYS_ALLOWED_SCOPES)
    if not narrowed:
        return None
    return sorted(narrowed)


def get_oauth_scopes_supported() -> list[str]:
    """Full `scopes_supported` list published in OAuth metadata.

    Used by the authorization server's `/.well-known/oauth-authorization-server`
    endpoint and by the MCP server's `/.well-known/oauth-protected-resource`
    (the latter generated at build time via `bin/build-mcp-oauth-scopes.py` so
    the protected resource cannot drift out of subset of the AS).

    Built from `UNPRIVILEGED_SCOPES`, so it excludes all three non-advertised
    classes: `INTERNAL_API_SCOPE_OBJECTS` (server-mint-only, e.g.
    `signal_scout_internal` — never user-grantable), `OAUTH_HIDDEN_SCOPES`
    (alpha / PAT-only), and `PRIVILEGED_SCOPES` (`llm_gateway:*`, admin-granted
    only). Discovery metadata shouldn't advertise scopes an OAuth client can't
    obtain self-serve. PAT validation uses `get_scope_descriptions()` directly
    and is unaffected.

    The Signals scout harness sandbox token carries `signal_scout_internal:write`,
    but it is minted by directly inserting an `OAuthAccessToken` row (see
    `posthog/temporal/oauth.py:create_oauth_access_token_for_user`) and never passes
    through `/authorize`, so the scope needs neither advertising here nor a place in
    `OAUTH2_PROVIDER["SCOPES"]`. Advertising it would let any OAuth client request it
    via user consent — a durable prompt-injection vector (scratchpad rows are read
    verbatim into every subsequent run's prompt).
    """
    visible = UNPRIVILEGED_SCOPES
    ordered = [
        f"{obj}:{action}" for obj in API_SCOPE_OBJECTS for action in API_SCOPE_ACTIONS if f"{obj}:{action}" in visible
    ]
    return list(OIDC_SCOPES) + ordered
