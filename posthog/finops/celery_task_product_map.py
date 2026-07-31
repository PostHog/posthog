"""Maps Celery task names to FinOps product attribution.

Used by the celery postrun signal handler to tag each usage meter with the
product and billable unit that owns the compute. Tasks are matched by their
function name (the last segment of the dotted Celery task path).

Canonical product names come from the FinOps v2 product enum. Unknown tasks
fall through to ``unallocated`` — a loud signal that prompts explicit mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CeleryTaskProduct:
    product: str
    billable_unit: str


_FALLBACK = CeleryTaskProduct(product="unallocated", billable_unit="shared")


@lru_cache(maxsize=1)
def _build_task_product_map() -> dict[str, CeleryTaskProduct]:
    # fmt: off
    return {
        # -- products/conversations --
        "send_teams_help":                          CeleryTaskProduct("conversations", "none"),
        "wake_snoozed_tickets":                     CeleryTaskProduct("conversations", "none"),
        "flush_pending_email_replies":              CeleryTaskProduct("conversations", "none"),
        "poll_teams_shared_channels":               CeleryTaskProduct("conversations", "none"),

        # -- products/customer_analytics --
        "process_custom_property_sync":             CeleryTaskProduct("customer_analytics", "events"),

        # -- products/data_warehouse + data_modeling --
        "send_external_data_failure_digest_task":   CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "send_external_data_failure_digest_catchup": CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "cleanup_expired_test_saved_queries":       CeleryTaskProduct("data_warehouse", "warehouse_rows"),

        # -- products/endpoints --
        "shadow_compare_ducklake_execution":        CeleryTaskProduct("endpoints", "compute_hours"),
        "deactivate_stale_materializations":        CeleryTaskProduct("endpoints", "compute_hours"),

        # -- products/error_tracking --
        "compute_error_tracking_recommendation":    CeleryTaskProduct("error_tracking", "exceptions"),
        "send_error_tracking_weekly_digest":        CeleryTaskProduct("error_tracking", "exceptions"),

        # -- products/feature_flags --
        "cleanup_stale_flag_definitions_expiry_tracking_task": CeleryTaskProduct("feature_flags", "flag_requests"),
        "cleanup_stale_flags_expiry_tracking_task": CeleryTaskProduct("feature_flags", "flag_requests"),
        "drain_flag_definitions_rebuild_requests":  CeleryTaskProduct("feature_flags", "flag_requests"),
        "feature_flags_local_eval_canary_task":     CeleryTaskProduct("feature_flags", "flag_requests"),
        "refresh_expiring_flag_definitions_cache_entries": CeleryTaskProduct("feature_flags", "flag_requests"),
        "refresh_expiring_flags_cache_entries":     CeleryTaskProduct("feature_flags", "flag_requests"),
        "sync_cross_region_flags_task":             CeleryTaskProduct("feature_flags", "flag_requests"),
        "compute_feature_flag_metrics":             CeleryTaskProduct("feature_flags", "flag_requests"),
        "find_flags_with_enriched_analytics":       CeleryTaskProduct("feature_flags", "flag_requests"),

        # -- products/logs --
        "logs_alert_events_cleanup_task":           CeleryTaskProduct("logs", "log_bytes"),

        # -- products/pulse + signals --
        "mark_stale_pulse_briefs_failed":           CeleryTaskProduct("signals", "signals_credits"),
        "sync_pending_signals_refund_credits":      CeleryTaskProduct("signals", "signals_credits"),

        # -- products/reminders --
        "process_due_reminders":                    CeleryTaskProduct("platform_and_support", "none"),

        # -- products/stamphog --
        "process_installation_event":               CeleryTaskProduct("devex-internal", "none"),
        "process_pull_request_event":               CeleryTaskProduct("devex-internal", "none"),
        "provision_and_send_digest":                CeleryTaskProduct("devex-internal", "none"),
        "send_daily_digests":                       CeleryTaskProduct("devex-internal", "none"),
        "send_digest_for_channel":                  CeleryTaskProduct("devex-internal", "none"),

        # -- products/tasks (PostHog Code sandbox management) --
        "refresh_stale_sandbox_custom_images_task": CeleryTaskProduct("posthog_code", "ai_credits"),

        # -- products/visual_review --
        "emit_run_processing_metrics":              CeleryTaskProduct("mcp", "none"),
        "process_run_diffs":                        CeleryTaskProduct("mcp", "none"),
        "post_approval_comment":                    CeleryTaskProduct("mcp", "none"),

        # -- products/web_analytics --
        "generate_heatmap_screenshot":              CeleryTaskProduct("web_analytics", "events"),
        "report_stuck_heatmap_screenshots":         CeleryTaskProduct("web_analytics", "events"),
        "sweep_web_analytics_achievement_team_tracks": CeleryTaskProduct("web_analytics", "events"),
        "lazy_precompute_revalidation":             CeleryTaskProduct("web_analytics", "events"),

        # -- products/wizard --
        "sync_wizard_event_definitions":            CeleryTaskProduct("posthog_ai", "ai_credits"),

        # -- products/approvals --
        "expire_old_change_requests":               CeleryTaskProduct("platform_and_support", "none"),
        "validate_pending_change_requests":         CeleryTaskProduct("platform_and_support", "none"),

        # -- products/streamlit_apps --
        "auto_restart_crashed_streamlit_sandboxes":  CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "cleanup_deleted_streamlit_app_zips":        CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "cleanup_expired_streamlit_oauth_tokens":    CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "prune_old_streamlit_app_versions":          CeleryTaskProduct("data_warehouse", "warehouse_rows"),
        "stop_idle_streamlit_sandboxes":             CeleryTaskProduct("data_warehouse", "warehouse_rows"),

        # -- shared: AI observability --
        "capture_ai_observability_report":          CeleryTaskProduct("ai_observability", "llm_events"),
        "send_ai_observability_usage_reports":      CeleryTaskProduct("ai_observability", "llm_events"),
        "capture_llm_analytics_report":             CeleryTaskProduct("ai_observability", "llm_events"),
        "send_llm_analytics_usage_reports":         CeleryTaskProduct("ai_observability", "llm_events"),

        # -- shared: billing --
        "send_org_usage_reports":                   CeleryTaskProduct("billing-internal", "none"),
        "send_all_org_usage_reports":               CeleryTaskProduct("billing-internal", "none"),
        "clickhouse_send_license_usage":            CeleryTaskProduct("billing-internal", "none"),
        "sync_all_organization_available_product_features": CeleryTaskProduct("billing-internal", "none"),
        "process_scheduled_changes":                CeleryTaskProduct("billing-internal", "none"),
        "calculate_decide_usage":                   CeleryTaskProduct("billing-internal", "none"),

        # -- shared: cohorts --
        "calculate_cohort":                         CeleryTaskProduct("shared", "events"),
        "insert_cohort_from_feature_flag":          CeleryTaskProduct("shared", "events"),
        "trigger_cohort_backfill_task":             CeleryTaskProduct("shared", "events"),
        "trigger_cohort_events_backfill_task":      CeleryTaskProduct("shared", "events"),

        # -- shared: platform internal --
        "redis_heartbeat":                          CeleryTaskProduct("platform-internal", "none"),
        "redis_celery_queue_depth":                 CeleryTaskProduct("platform-internal", "none"),
        "pg_table_cache_hit_rate":                  CeleryTaskProduct("platform-internal", "none"),
        "pg_plugin_server_query_timing":            CeleryTaskProduct("platform-internal", "none"),
        "clickhouse_row_count":                     CeleryTaskProduct("platform-internal", "none"),
        "clickhouse_errors_count":                  CeleryTaskProduct("platform-internal", "none"),
        "clickhouse_part_count":                    CeleryTaskProduct("platform-internal", "none"),
        "clickhouse_mutation_count":                CeleryTaskProduct("platform-internal", "none"),
        "clickhouse_materialize_columns":           CeleryTaskProduct("platform-internal", "none"),
        "update_event_partitions":                  CeleryTaskProduct("platform-internal", "none"),
        "check_async_migration_health":             CeleryTaskProduct("platform-internal", "none"),
        "run_async_migration":                      CeleryTaskProduct("platform-internal", "none"),
        "start_poll_query_performance":             CeleryTaskProduct("platform-internal", "none"),
        "poll_query_performance":                   CeleryTaskProduct("platform-internal", "none"),
        "demo_reset_master_team":                   CeleryTaskProduct("platform-internal", "none"),
        "delete_expired_exported_assets":           CeleryTaskProduct("platform-internal", "none"),
        "background_delete_model_task":             CeleryTaskProduct("platform-internal", "none"),
        "sync_js_snippet_manifest":                 CeleryTaskProduct("platform-internal", "none"),
        "capture_task_run_state_metrics":            CeleryTaskProduct("platform-internal", "none"),
        "clean_stale_partials":                     CeleryTaskProduct("platform-internal", "none"),
        "clear_expired_sessions":                   CeleryTaskProduct("platform-internal", "none"),
        "delete_expired_delegation_invites":        CeleryTaskProduct("platform-internal", "none"),
        "ingestion_lag":                            CeleryTaskProduct("platform-internal", "none"),
        "refresh_activity_log_fields_cache":        CeleryTaskProduct("platform-internal", "none"),
        "sync_feature_flag_last_called":            CeleryTaskProduct("platform-internal", "none"),

        # -- shared: clickhouse ops --
        "clickhouse_clear_removed_data":            CeleryTaskProduct("shared", "events"),
        "clear_clickhouse_deleted_person":          CeleryTaskProduct("shared", "events"),

        # -- shared: email/notifications --
        "send_fatal_plugin_error":                  CeleryTaskProduct("platform_and_support", "none"),
        "send_hog_function_disabled":               CeleryTaskProduct("platform_and_support", "none"),
        "send_canary_email":                        CeleryTaskProduct("platform_and_support", "none"),
        "send_email_change_emails":                 CeleryTaskProduct("platform_and_support", "none"),
        "send_async_migration_complete_email":      CeleryTaskProduct("platform_and_support", "none"),
        "send_async_migration_errored_email":       CeleryTaskProduct("platform_and_support", "none"),
        "send_discussions_mentioned":               CeleryTaskProduct("platform_and_support", "none"),
        "send_hog_functions_daily_digest":          CeleryTaskProduct("platform_and_support", "none"),
        "send_project_secret_api_key_exposed":      CeleryTaskProduct("platform_and_support", "none"),
        "send_matview_failure_digest":              CeleryTaskProduct("platform_and_support", "none"),

        # -- shared: exports --
        "export_asset":                             CeleryTaskProduct("shared", "shared"),

        # -- shared: surveys --
        "stop_surveys_reached_target":              CeleryTaskProduct("surveys", "survey_responses"),
        "update_survey_iteration":                  CeleryTaskProduct("surveys", "survey_responses"),
        "update_survey_adaptive_sampling":          CeleryTaskProduct("surveys", "survey_responses"),
        "sync_all_surveys_cache":                   CeleryTaskProduct("surveys", "survey_responses"),

        # -- shared: CDP --
        "fatal_plugin_error":                       CeleryTaskProduct("realtime_destinations", "cdp_invocations"),
        "hog_function_state_transition":            CeleryTaskProduct("realtime_destinations", "cdp_invocations"),

        # -- shared: AI gateway --
        "refresh_gateway_credentials":              CeleryTaskProduct("ai_gateway", "none"),
        "drain_gateway_credential_last_used_task":  CeleryTaskProduct("ai_gateway", "none"),
        "refresh_expiring_llm_gateway_policy_cache_entries": CeleryTaskProduct("ai_gateway", "none"),
        "invalidate_archived_prompt_versions_cache_task": CeleryTaskProduct("ai_gateway", "none"),

        # -- shared: auth cache --
        "invalidate_token_cache_task":              CeleryTaskProduct("platform_and_support", "none"),
        "invalidate_user_tokens_task":              CeleryTaskProduct("platform_and_support", "none"),
        "verify_and_fix_auth_token_cache_task":     CeleryTaskProduct("platform_and_support", "none"),
        "verify_and_fix_flag_definitions_cache_task": CeleryTaskProduct("platform_and_support", "none"),
        "verify_and_fix_flags_cache_task":          CeleryTaskProduct("platform_and_support", "none"),
        "verify_and_fix_team_metadata_cache_task":  CeleryTaskProduct("platform_and_support", "none"),
        "refresh_expiring_team_metadata_cache_entries": CeleryTaskProduct("platform_and_support", "none"),
        "cleanup_stale_expiry_tracking_task":       CeleryTaskProduct("platform_and_support", "none"),
        "refresh_expiring_remote_config_cache_entries": CeleryTaskProduct("platform_and_support", "none"),
        "cleanup_stale_remote_config_expiry_tracking_task": CeleryTaskProduct("platform_and_support", "none"),
        "sync_all_remote_configs":                  CeleryTaskProduct("platform_and_support", "none"),

        # -- shared: integrations --
        "refresh_integrations":                     CeleryTaskProduct("platform_and_support", "none"),

        # -- shared: cache warming --
        "schedule_warming_for_teams_task":          CeleryTaskProduct("shared", "shared"),

        # -- shared: PostHog Code --
        "kill_stale_queued_task_runs":              CeleryTaskProduct("posthog_code", "ai_credits"),
        "redispatch_orphaned_queued_task_runs":     CeleryTaskProduct("posthog_code", "ai_credits"),

        # -- shared: health checks --
        "evaluate_health_check_for_team":           CeleryTaskProduct("platform-internal", "none"),

        # -- shared: push notifications --
        "send_push_notification":                   CeleryTaskProduct("platform_and_support", "none"),
    }
    # fmt: on


def resolve_celery_task_product(task_name: str) -> CeleryTaskProduct:
    """Resolve a Celery task's dotted name to its product attribution.

    Matches by the function name (last segment of the dotted path). Falls back
    to ``unallocated`` for unknown tasks — a deliberate gap signal.
    """
    fn_name = task_name.rsplit(".", 1)[-1]
    return _build_task_product_map().get(fn_name, _FALLBACK)
