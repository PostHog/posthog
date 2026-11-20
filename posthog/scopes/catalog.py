"""Every scope object and action, and the scope strings PostHog's own code uses as markers."""

from collections.abc import Iterable
from typing import Literal, get_args

## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes

# A new scope object also needs a `ScopeDoc` in the owning product's `backend/scopes.py`, or in
# `posthog/scope_docs.py` for a core scope, unless it is in
# `exposure.SCOPE_OBJECTS_OMITTED_FROM_PICKERS`. The scope pickers take everything they show about the object from there.
# posthog/test/repo_invariants/test_scope_docs.py fails until it exists.
#
# The frontend `APIScopeObject` type needs no edit. `hogli build:openapi` generates it from
# `exposure.GRANTABLE_API_SCOPE_OBJECTS`, through the `resource` choice fields of the access
# control serializers.
#
# The `OAUTH_SCOPES_SUPPORTED` and `OAUTH_SCOPES_HIDDEN` lists at
# `services/mcp/src/lib/oauth-scopes.generated.ts` and `frontend/src/lib/oauthScopes.generated.ts`
# are generated from this package via `posthog/scopes_projection.py`. Run
# `hogli build:projections` to regenerate after editing it.
APIScopeObject = Literal[
    "action",
    "access_control",
    "account",
    # Notes on Customer Analytics accounts, split off `account` so a note can be written without the rest of
    # the account surface (rename, delete, properties, relationships).
    "account_note",
    "activity_log",
    "alert",
    "annotation",
    "approvals",
    "autoresearch",
    "batch_export",
    "batch_import",
    "batch_import_support",
    "billing",
    "business_knowledge",
    "canvas",
    "clickhouse_test_cluster_perf",
    "code_review",
    "code_review_approval",
    "cohort",
    "comment",
    "conversation",
    "context_layer_internal",
    "cross_project_dashboard",
    "customer_analytics",
    "customer_task",
    "customer_journey",
    "customer_profile_config",
    "data_catalog",
    "data_catalog_approval",
    "data_deletion",
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
    # Suggesting a change to a workflow, and nothing else. Separate from `hog_flow` so the scout can
    # propose without holding the scope that publishes, updates or test-sends a workflow. INTERNAL.
    "hog_flow_proposal",
    "hog_function",
    "inbox",
    "ingestion_warning",
    "insight",
    "insight_variable",
    "integration",
    "interactive_run",
    "internal_run",
    "knowledge_writer",
    "legal_document",
    "link",  # Endpoints are gone; kept advertised until desktop OAuth clients stop requesting it.
    "live_debugger",  # Endpoints are gone; kept advertised until desktop OAuth clients stop requesting it.
    "llm_analytics",
    "ai_observability_clusters",
    "llm_gateway",
    "llm_playground",
    "llm_prompt",
    "llm_provider_key",
    "llm_skill",
    "logs",
    "loop",  # Endpoints are gone; kept advertised until desktop OAuth clients stop requesting it.
    "marketing_analytics",
    "mcp_builtin_agent",
    "mcp_analytics",
    "mcp_registry",  # Endpoints are gone; kept advertised until OAuth clients stop requesting it.
    "messaging_preference",
    "metrics",
    "notebook",
    "offline_evaluation_ingestion",
    "organization",
    "organization_integration",
    "organization_member",
    "person",
    "plugin",
    # Opening and following tickets with PostHog's own support team, as the signed-in user.
    "posthog_support",
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
    "scout_experiment_internal",
    "signal_scout",
    "signal_scout_internal",
    "signal_scout_monitoring",
    "signal_scout_report",
    "signal_scratchpad_internal",
    "signal_usage",
    "slack_run",
    "streamlit_app",
    "subscription",
    "support_ticket",
    "survey",
    "tagger",
    "ticket",
    "task",
    "today",
    "toolbar",
    "tracing",
    "transactional_email",
    "field_note",
    "uploaded_media",
    "usage_metric",
    "user",
    "vision_action",  # Endpoints are gone; kept advertised until desktop OAuth clients stop requesting it.
    "vision_alert",
    "visual_review",
    "warehouse_objects",
    "warehouse_table",
    "warehouse_view",
    "web_analytics",
    "webhook",
    "wizard_session",
    "wizard_run",
    "workload_trust_policy",
    "workload_trust_policy_request",
]

# Server-only provenance markers hidden from user-controlled scope selectors.
MCP_BUILT_IN_AGENT_SCOPE = "mcp_builtin_agent:read"

SLACK_RUN_SCOPE = "slack_run:read"

SCOUT_MONITORING_RESULT_SCOPE = "signal_scout_monitoring:write"

APIScopeActions = Literal[
    "read",
    "write",
]

APIScopeObjectOrNotSupported = Literal[
    APIScopeObject,
    "INTERNAL",
]

# Every scope object, internal ones included. Most code wants one of the narrower sets in `exposure`.
API_SCOPE_OBJECTS: tuple[APIScopeObject, ...] = get_args(APIScopeObject)

API_SCOPE_ACTIONS: tuple[APIScopeActions, ...] = get_args(APIScopeActions)


# PostHog desktop and agent builds already shipped request these scope objects by their old names,
# CIMD and DCR metadata may still declare them, and stored keys, ceilings and tokens hold both
# names until a follow-up migration drops the old ones. Every place a scope string enters OAuth or
# a key write path runs it through `translate_renamed_scopes`, so nothing downstream sees an old
# name. Remove the mapping once builds that request the old names have aged out and the old names
# are gone from storage.
RENAMED_OAUTH_SCOPE_OBJECTS: dict[str, str] = {
    "review_hog": "code_review",
    "stamphog": "code_review_approval",
}


def translate_renamed_scopes(scopes: Iterable[str]) -> list[str]:
    """`scopes` with every scope of a renamed object written under its new name, order kept, deduplicated."""
    translated = []
    for scope in scopes:
        scope_object, separator, action = scope.partition(":")
        new_object = RENAMED_OAUTH_SCOPE_OBJECTS.get(scope_object)
        translated.append(f"{new_object}{separator}{action}" if new_object and separator else scope)
    return list(dict.fromkeys(translated))
