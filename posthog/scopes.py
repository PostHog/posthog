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
    "activity_log",
    "alert",
    "annotation",
    "approvals",
    "batch_export",
    "batch_import",
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
    "llm_analytics",
    "llm_gateway",
    "llm_prompt",
    "llm_provider_key",
    "llm_skill",
    "logs",
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
    "revenue_analytics",
    "session_recording",
    "session_recording_playlist",
    "sharing_configuration",
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
    "user_interview_DO_NOT_USE",  # This is a super alpha product, so only exposing here for internal personal API key access
    "visual_review",
    "warehouse_objects",
    "warehouse_table",
    "warehouse_view",
    "web_analytics",
    "webhook",
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
INTERNAL_API_SCOPE_OBJECTS: frozenset[APIScopeObject] = frozenset({"clickhouse_test_cluster_perf"})

# Scope objects available via personal API keys but never advertised through
# OAuth metadata. Used for alpha / not-yet-public products where a user can
# manually paste the scope into a PAT but where we don't want OAuth-based
# clients (the consent screen, MCP, third-party apps) to discover it.
OAUTH_HIDDEN_SCOPE_OBJECTS: frozenset[APIScopeObject] = frozenset({"user_interview_DO_NOT_USE"})

PROJECT_SECRET_API_KEY_ALLOWED_API_SCOPE_ACTION: list[tuple[APIScopeObject, APIScopeActions]] = [("endpoint", "read")]


def get_scope_descriptions() -> dict[str, str]:
    return {
        f"{obj}:{action}": f"{action.capitalize()} access to {obj}"
        for obj in API_SCOPE_OBJECTS
        if obj not in INTERNAL_API_SCOPE_OBJECTS
        for action in API_SCOPE_ACTIONS
    }


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

    Excludes scopes in `OAUTH_HIDDEN_SCOPE_OBJECTS` so OAuth-based clients
    (MCP, third-party apps) don't discover scopes intended only for manually
    issued personal API keys. PAT validation uses `get_scope_descriptions()`
    directly and is unaffected.
    """
    visible = (
        f"{obj}:{action}"
        for obj in API_SCOPE_OBJECTS
        if obj not in INTERNAL_API_SCOPE_OBJECTS and obj not in OAUTH_HIDDEN_SCOPE_OBJECTS
        for action in API_SCOPE_ACTIONS
    )
    return list(OIDC_SCOPES) + list(visible)
