import type { CloudRegion } from "./regions";

export const POSTHOG_US_CLIENT_ID = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W";
export const POSTHOG_EU_CLIENT_ID = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9";
export const POSTHOG_DEV_CLIENT_ID = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ";

// Explicit scopes instead of "*". Mirrors scopes_supported at
// /.well-known/oauth-authorization-server (OAUTH_SCOPES_SUPPORTED in the API's
// services/mcp/src/lib/oauth-scopes.generated.ts), plus privileged llm_gateway:read
// which the advertised set excludes. The LLM gateway requires that scope; it is
// granted only because this app's OAuth ceiling is seeded to
// ["@default", "llm_gateway:read"] in US + EU.
//
// That generated file also exports OAUTH_SCOPES_HIDDEN (batch_import_support,
// query_performance, wizard_session). Never copy those in: they are staff-only
// and subtracted out of UNPRIVILEGED_SCOPES, so "@default" can never cover them
// and /authorize rejects the whole request with invalid_scope.
//
// Deploy-order guardrail: NEVER ship a non-"*" OAUTH_SCOPES set (or bump
// OAUTH_SCOPE_VERSION off a build that still requests "*") until that ceiling is
// seeded in both regions. A non-empty ceiling rejects scope=* at /authorize, and
// an empty/unseeded ceiling rejects privileged llm_gateway:read. #3411 shipped
// the explicit list bundled with loops without seeding; prod login broke and was
// reverted in #3668. Keep this comment when regenerating the list.
//
// Regenerate from the live advertised list + llm_gateway:read last; bump
// OAUTH_SCOPE_VERSION whenever the set changes so installs re-authorize.
export const OAUTH_SCOPES = [
  "openid",
  "profile",
  "email",
  "action:read",
  "action:write",
  "access_control:read",
  "access_control:write",
  "account:read",
  "account:write",
  "activity_log:read",
  "activity_log:write",
  "alert:read",
  "alert:write",
  "annotation:read",
  "annotation:write",
  "approvals:read",
  "approvals:write",
  "batch_export:read",
  "batch_export:write",
  "batch_import:read",
  "batch_import:write",
  "business_knowledge:read",
  "business_knowledge:write",
  "canvas:read",
  "canvas:write",
  "cohort:read",
  "cohort:write",
  "comment:read",
  "comment:write",
  "conversation:read",
  "conversation:write",
  "customer_analytics:read",
  "customer_analytics:write",
  "customer_journey:read",
  "customer_journey:write",
  "customer_profile_config:read",
  "customer_profile_config:write",
  "data_catalog:read",
  "data_catalog:write",
  "data_catalog_approval:read",
  "data_catalog_approval:write",
  "dashboard:read",
  "dashboard:write",
  "event_filter:read",
  "event_filter:write",
  "dashboard_template:read",
  "dashboard_template:write",
  "dataset:read",
  "dataset:write",
  "early_access_feature:read",
  "early_access_feature:write",
  "endpoint:read",
  "endpoint:write",
  "engineering_analytics:read",
  "engineering_analytics:write",
  "error_tracking:read",
  "error_tracking:write",
  "evaluation:read",
  "evaluation:write",
  "element:read",
  "element:write",
  "event_definition:read",
  "event_definition:write",
  "experiment:read",
  "experiment:write",
  "experiment_holdout:read",
  "experiment_holdout:write",
  "experiment_saved_metric:read",
  "experiment_saved_metric:write",
  "export:read",
  "export:write",
  "external_data_schema:read",
  "external_data_schema:write",
  "external_data_source:read",
  "external_data_source:write",
  "feature_flag:read",
  "feature_flag:write",
  "file_system:read",
  "file_system:write",
  "file_system_shortcut:read",
  "file_system_shortcut:write",
  "group:read",
  "group:write",
  "health_issue:read",
  "health_issue:write",
  "heatmap:read",
  "heatmap:write",
  "hog_flow:read",
  "hog_flow:write",
  "hog_function:read",
  "hog_function:write",
  "ingestion_warning:read",
  "ingestion_warning:write",
  "insight:read",
  "insight:write",
  "insight_variable:read",
  "insight_variable:write",
  "integration:read",
  "integration:write",
  "legal_document:read",
  "legal_document:write",
  "link:read",
  "link:write",
  "live_debugger:read",
  "live_debugger:write",
  "llm_analytics:read",
  "llm_analytics:write",
  "ai_observability_clusters:read",
  "ai_observability_clusters:write",
  "llm_playground:read",
  "llm_playground:write",
  "llm_prompt:read",
  "llm_prompt:write",
  "llm_provider_key:read",
  "llm_provider_key:write",
  "llm_skill:read",
  "llm_skill:write",
  "logs:read",
  "logs:write",
  "loop:read",
  "loop:write",
  "marketing_analytics:read",
  "marketing_analytics:write",
  "mcp_analytics:read",
  "mcp_analytics:write",
  "metrics:read",
  "metrics:write",
  "notebook:read",
  "notebook:write",
  "organization:read",
  "organization:write",
  "organization_integration:read",
  "organization_integration:write",
  "organization_member:read",
  "organization_member:write",
  "person:read",
  "person:write",
  "plugin:read",
  "plugin:write",
  "product_enablement:read",
  "product_enablement:write",
  "product_tour:read",
  "product_tour:write",
  "project:read",
  "project:write",
  "property_definition:read",
  "property_definition:write",
  "query:read",
  "query:write",
  "replay_scanner:read",
  "replay_scanner:write",
  "review_hog:read",
  "review_hog:write",
  "revenue_analytics:read",
  "revenue_analytics:write",
  "session_recording:read",
  "session_recording:write",
  "session_recording_playlist:read",
  "session_recording_playlist:write",
  "sharing_configuration:read",
  "sharing_configuration:write",
  "signal_scout:read",
  "signal_scout:write",
  "stamphog:read",
  "stamphog:write",
  "streamlit_app:read",
  "streamlit_app:write",
  "subscription:read",
  "subscription:write",
  "survey:read",
  "survey:write",
  "tagger:read",
  "tagger:write",
  "ticket:read",
  "ticket:write",
  "task:read",
  "task:write",
  "toolbar:read",
  "toolbar:write",
  "tracing:read",
  "tracing:write",
  "field_note:read",
  "field_note:write",
  "uploaded_media:read",
  "uploaded_media:write",
  "usage_metric:read",
  "usage_metric:write",
  "user:read",
  "user:write",
  "user_interview:read",
  "user_interview:write",
  "vision_action:read",
  "vision_action:write",
  "visual_review:read",
  "visual_review:write",
  "warehouse_objects:read",
  "warehouse_objects:write",
  "warehouse_table:read",
  "warehouse_table:write",
  "warehouse_view:read",
  "warehouse_view:write",
  "web_analytics:read",
  "web_analytics:write",
  "webhook:read",
  "webhook:write",
  // Privileged: embedded agent model calls go through PostHog's LLM gateway
  // (gateway.{region}.posthog.com), which requires this scope. Not in the
  // advertised set above; granted via this app's seeded ceiling.
  "llm_gateway:read",
];

// v6: the server grew the `canvas` scope (PostHog/posthog#73874). On apps with a seeded
// scope ceiling, /oauth/authorize narrows a `*` request to the ceiling ENUMERATED AT GRANT
// TIME and refresh never widens it — so sessions granted before the scope existed 403 on
// /canvases/ forever. Bumping forces one re-auth, whose fresh grant includes it. The same
// applies to every future server-side scope addition the app relies on, even when
// OAUTH_SCOPES itself is unchanged.
// v7: "*" replaced with the explicit list above.
export const OAUTH_SCOPE_VERSION = 7;

// Token refresh settings
export const TOKEN_REFRESH_BUFFER_MS = 30 * 60 * 1000; // 30 minutes before expiry
export const TOKEN_REFRESH_FORCE_MS = 60 * 1000; // Force refresh when <1 min to expiry, even with active sessions

export function getOauthClientIdFromRegion(region: CloudRegion): string {
  switch (region) {
    case "us":
      return POSTHOG_US_CLIENT_ID;
    case "eu":
      return POSTHOG_EU_CLIENT_ID;
    case "dev":
      return POSTHOG_DEV_CLIENT_ID;
  }
}
