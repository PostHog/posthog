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
    "agent_application",
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
    "desktop_recording",
    "early_access_feature",
    "endpoint",
    "error_tracking",
    "evaluation",
    "element",
    "event_definition",
    "experiment",
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
    "insight",
    "insight_variable",
    "integration",
    "legal_document",
    "link",
    "live_debugger",
    "ai_gateway",
    "llm_analytics",
    "llm_gateway",
    "llm_prompt",
    "llm_provider_key",
    "llm_skill",
    "logs",
    "marketing_analytics",
    "metrics",
    "notebook",
    "organization",
    "organization_integration",
    "organization_member",
    "person",
    "persisted_folder",
    "plugin",
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
    "streamlit_app",
    "subscription",
    "survey",
    "tagger",
    "ticket",
    "task",
    "tracing",
    "uploaded_media",
    "usage_metric",
    "user",
    "user_interview",  # Alpha product — access gated by feature flag at the MCP/API layer rather than by hiding the scope.
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
        "query_performance",
        # Sandbox-only writes for the headless Signals agent (memory create/delete,
        # finding emit). Read access for the same surface lives on the public
        # `signal_scout` object so user-grantable PAKs can still inspect runs/memory.
        "signal_scout_internal",
    }
)

# Scope objects available via personal API keys but never advertised through
# OAuth metadata. Used for alpha / not-yet-public products where a user can
# manually paste the scope into a PAT but where we don't want OAuth-based
# clients (the consent screen, MCP, third-party apps) to discover it.
OAUTH_HIDDEN_SCOPE_OBJECTS: frozenset[APIScopeObject] = frozenset({"metrics", "wizard_session"})

PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[APIScopeObject, APIScopeActions]] = [("endpoint", "read")]

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
