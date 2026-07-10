from random import randrange
from typing import Any

from django.conf import settings

from celery import Celery
from celery.canvas import Signature
from celery.schedules import crontab

from posthog.caching.warming import schedule_warming_for_teams_task
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.tasks.ai_observability_usage_report import send_ai_observability_usage_reports
from posthog.tasks.auth_token_cache_verification import verify_and_fix_auth_token_cache_task
from posthog.tasks.email import (
    EXTERNAL_DATA_DIGEST_DAY_BOUNDARY_HOUR_UTC,
    send_error_tracking_weekly_digest,
    send_hog_functions_daily_digest,
    send_matview_failure_digest,
)
from posthog.tasks.gateway_credential import drain_gateway_credential_last_used_task, refresh_gateway_credentials
from posthog.tasks.hypercache_verification import (
    verify_and_fix_flag_definitions_cache_task,
    verify_and_fix_flag_definitions_without_cohorts_cache_task,
    verify_and_fix_flags_cache_task,
    verify_and_fix_team_metadata_cache_task,
)
from posthog.tasks.integrations import refresh_integrations
from posthog.tasks.js_snippet_versioning import sync_js_snippet_manifest
from posthog.tasks.remote_config import (
    cleanup_stale_remote_config_expiry_tracking_task,
    refresh_expiring_remote_config_cache_entries,
    sync_all_remote_configs,
)
from posthog.tasks.surveys import sync_all_surveys_cache
from posthog.tasks.tasks import (
    calculate_cohort,
    calculate_decide_usage,
    capture_task_run_state_metrics,
    check_async_migration_health,
    check_flags_to_rollback,
    clean_stale_partials,
    clear_clickhouse_deleted_person,
    clear_expired_sessions,
    clickhouse_clear_removed_data,
    clickhouse_errors_count,
    clickhouse_materialize_columns,
    clickhouse_mutation_count,
    clickhouse_part_count,
    clickhouse_row_count,
    clickhouse_send_license_usage,
    delete_expired_delegation_invites,
    delete_expired_exported_assets,
    find_flags_with_enriched_analytics,
    ingestion_lag,
    kill_stale_queued_task_runs,
    pg_plugin_server_query_timing,
    pg_table_cache_hit_rate,
    process_scheduled_changes,
    redis_celery_queue_depth,
    redis_heartbeat,
    redispatch_orphaned_queued_task_runs,
    refresh_activity_log_fields_cache,
    send_org_usage_reports,
    start_poll_query_performance,
    stop_surveys_reached_target,
    sync_all_organization_available_product_features,
    sync_feature_flag_last_called,
    update_event_partitions,
    update_survey_adaptive_sampling,
    update_survey_iteration,
)
from posthog.tasks.team_llm_gateway_policy import refresh_expiring_llm_gateway_policy_cache_entries
from posthog.tasks.team_metadata import cleanup_stale_expiry_tracking_task, refresh_expiring_team_metadata_cache_entries
from posthog.utils import get_crontab, get_instance_region

from products.approvals.backend.tasks import expire_old_change_requests, validate_pending_change_requests
from products.conversations.backend.tasks import (
    flush_pending_email_replies,
    poll_teams_shared_channels,
    wake_snoozed_tickets,
)
from products.data_modeling.backend.facade.tasks import cleanup_expired_test_saved_queries
from products.data_warehouse.backend.facade.tasks import send_external_data_failure_digest_catchup
from products.endpoints.backend.facade.tasks import deactivate_stale_materializations
from products.feature_flags.backend.tasks import (
    cleanup_stale_flag_definitions_expiry_tracking_task,
    cleanup_stale_flags_expiry_tracking_task,
    compute_feature_flag_metrics,
    drain_flag_definitions_rebuild_requests,
    feature_flags_local_eval_canary_task,
    refresh_expiring_flag_definitions_cache_entries,
    refresh_expiring_flags_cache_entries,
)
from products.logs.backend.facade.tasks import logs_alert_events_cleanup_task
from products.mcp_store.backend.facade.tasks import maintain_shared_installations
from products.reminders.backend.tasks import process_due_reminders
from products.streamlit_apps.backend.facade.api import (
    auto_restart_crashed_streamlit_sandboxes,
    cleanup_deleted_streamlit_app_zips,
    cleanup_expired_streamlit_oauth_tokens,
    prune_old_streamlit_app_versions,
    stop_idle_streamlit_sandboxes,
)
from products.web_analytics.backend.achievements.tasks import sweep_web_analytics_achievement_team_tracks
from products.web_analytics.backend.tasks.heatmap_screenshot import report_stuck_heatmap_screenshots

TWENTY_FOUR_HOURS = 24 * 60 * 60

# Organizations with delayed data ingestion that need delayed usage report re-runs
# This is a temporary solution until we switch event usage queries from timestamp to created_at
DELAYED_ORGS_EU: list[str] = [
    "018beddd-5eb1-0000-7953-5a5b982e80bf",
    "01975ab3-7ec5-0000-9751-a89cbc971419",
]
DELAYED_ORGS_US: list[str] = []


def estimate_crontab_interval_seconds(schedule: crontab) -> int:
    """
    Estimate interval between crontab executions from the expanded time sets.

    Works by analyzing the crontab's minute/hour/day sets to find the smallest
    gap between consecutive executions. Handles wrap-around (e.g., minute 50 to 0).
    """
    minutes = sorted(schedule.minute)
    hours = sorted(schedule.hour)
    days_of_week = sorted(schedule.day_of_week)
    days_of_month = sorted(schedule.day_of_month)

    all_hours = len(hours) == 24
    all_days = len(days_of_week) == 7 and len(days_of_month) == 31

    if all_hours and all_days:
        # Interval is based on minutes
        if len(minutes) == 60:
            return 60  # every minute
        elif len(minutes) > 1:
            # Find smallest gap between consecutive minutes (including wrap-around)
            gaps = [minutes[i + 1] - minutes[i] for i in range(len(minutes) - 1)]
            gaps.append(60 - minutes[-1] + minutes[0])
            return min(gaps) * 60
        else:
            return 3600  # single minute = hourly

    if all_days:
        # Check hour-based intervals
        if len(hours) > 1:
            gaps = [hours[i + 1] - hours[i] for i in range(len(hours) - 1)]
            gaps.append(24 - hours[-1] + hours[0])
            return min(gaps) * 3600
        else:
            return 86400  # daily

    # Weekly or more complex - default to daily for safety
    return 86400


def add_periodic_task_with_expiry(
    sender: Celery,
    schedule: crontab,
    task_signature: Signature,
    name: str,
    expires_seconds: float | None = None,
) -> None:
    """
    Schedule a periodic task with expiry to prevent duplicate processing when workers fall behind.

    Expiry defaults to 1.5x the estimated interval from the crontab schedule, but can be overridden.

    ⚠️  WARNING: DO NOT USE sender.add_periodic_task() DIRECTLY FOR INTERVALS >= 60 SECONDS  ⚠️

    Celery beat resets interval countdowns on every restart. With beat pods restarting every
    5-10 minutes, any interval-based schedule longer than that will NEVER run. Always use this
    helper with a crontab schedule instead. Sub-minute intervals are okay since they run more
    frequently than beat restarts.
    """
    if expires_seconds is None:
        expires_seconds = estimate_crontab_interval_seconds(schedule) * 1.5
    sender.add_periodic_task(
        schedule,
        task_signature,
        name=name,
        expires=expires_seconds,
    )


def setup_periodic_tasks(sender: Celery, **kwargs: Any) -> None:
    # Short-interval heartbeat tasks (<60s) use intervals since cron minimum is 1 minute.
    # These are fine because they run more frequently than beat restarts.
    if not settings.DEBUG:
        sender.add_periodic_task(10, redis_celery_queue_depth.s(), name="10 sec queue probe")

    sender.add_periodic_task(
        60,
        capture_task_run_state_metrics.s(),
        name="tasks run state metrics",
    )

    sender.add_periodic_task(10, redis_heartbeat.s(), name="10 sec heartbeat")
    sender.add_periodic_task(
        QueryStatusManager.POLL_INTERVAL_SECONDS,
        start_poll_query_performance.s(),
        name="query performance heartbeat",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="0"),
        schedule_warming_for_teams_task.s(),
        name="schedule warming for largest teams",
    )

    # Team metadata cache sync - hourly
    sender.add_periodic_task(
        crontab(hour="*", minute="0"),
        refresh_expiring_team_metadata_cache_entries.s(),
        name="team metadata cache sync",
    )

    # Team metadata expiry tracking cleanup - daily at 3 AM
    sender.add_periodic_task(
        crontab(hour="3", minute="0"),
        cleanup_stale_expiry_tracking_task.s(),
        name="team metadata expiry tracking cleanup",
    )

    # LLM gateway policy cache sync - hourly at :05 to stagger from team_metadata at :00
    sender.add_periodic_task(
        crontab(hour="*", minute="5"),
        refresh_expiring_llm_gateway_policy_cache_entries.s(),
        name="llm-gateway policy cache sync",
    )

    # Gateway credential cache sync - hourly at :10 to stagger from the others
    sender.add_periodic_task(
        crontab(hour="*", minute="10"),
        refresh_gateway_credentials.s(),
        name="gateway credential cache sync",
    )

    # Gateway credential last-used drain - every 5 min; the only writer of last_used_at for gateway keys.
    sender.add_periodic_task(
        crontab(minute="*/5"),
        drain_gateway_credential_last_used_task.s(),
        name="gateway credential last-used drain",
    )

    # Stale QUEUED task run cleanup - hourly
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="0"),
        kill_stale_queued_task_runs.s(),
        name="kill stale queued task runs",
    )

    # Re-dispatch orphaned QUEUED task runs whose on_commit dispatch was lost - every 2 minutes
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        redispatch_orphaned_queued_task_runs.s(),
        name="redispatch orphaned queued task runs",
    )

    # Flags cache sync - hourly
    sender.add_periodic_task(
        crontab(hour="*", minute="15"),
        refresh_expiring_flags_cache_entries.s(),
        name="refresh expiring flags cache entries",
    )

    # Flags cache expiry tracking cleanup - daily at 3:15 AM
    sender.add_periodic_task(
        crontab(hour="3", minute="15"),
        cleanup_stale_flags_expiry_tracking_task.s(),
        name="flags cache expiry tracking cleanup",
    )

    # Feature flag metrics for Grafana dashboards - hourly at minute 30
    sender.add_periodic_task(
        crontab(hour="*", minute="30"),
        compute_feature_flag_metrics.s(),
        name="compute feature flag metrics",
    )

    # Flag definitions cache refresh - hourly at minute 35
    sender.add_periodic_task(
        crontab(hour="*", minute="35"),
        refresh_expiring_flag_definitions_cache_entries.s(),
        name="refresh expiring flag definitions cache entries",
    )

    # Flag definitions cache expiry tracking cleanup - daily at 3:30 AM
    sender.add_periodic_task(
        crontab(hour="3", minute="30"),
        cleanup_stale_flag_definitions_expiry_tracking_task.s(),
        name="flag definitions cache expiry tracking cleanup",
    )

    # Remote config (array/config.json) cache refresh - hourly at minute 45
    sender.add_periodic_task(
        crontab(hour="*", minute="45"),
        refresh_expiring_remote_config_cache_entries.s(),
        name="refresh expiring remote config cache entries",
    )

    # Remote config cache expiry tracking cleanup - daily at 3:45 AM
    sender.add_periodic_task(
        crontab(hour="3", minute="45"),
        cleanup_stale_remote_config_expiry_tracking_task.s(),
        name="remote config cache expiry tracking cleanup",
    )

    # Team metadata cache verification - hourly at minute 20
    add_periodic_task_with_expiry(
        sender,
        crontab(hour="*", minute="20"),
        verify_and_fix_team_metadata_cache_task.s(),
        name="verify and fix team metadata cache",
        expires_seconds=60 * 60,
    )

    # Flags cache verification - every 30 minutes
    # Task takes ~8-10 minutes with 250-team batch size
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/30"),
        verify_and_fix_flags_cache_task.s(),
        name="verify and fix flags cache",
        expires_seconds=30 * 60,
    )

    # Verify flag definitions cache without cohorts - hourly at minute 10
    # Minute 10 reduces the likelihood of overlapping with team_metadata verification at minute 20 and helps spread load.
    add_periodic_task_with_expiry(
        sender,
        crontab(hour="*", minute="10"),
        verify_and_fix_flag_definitions_without_cohorts_cache_task.s(),
        name="verify and fix flag definitions cache (without cohorts)",
        expires_seconds=60 * 60,
    )

    # Flag definitions cache verification (with cohorts) - hourly at minute 50
    add_periodic_task_with_expiry(
        sender,
        crontab(hour="*", minute="50"),
        verify_and_fix_flag_definitions_cache_task.s(),
        name="verify and fix flag definitions cache (with cohorts)",
        expires_seconds=60 * 60,
    )

    # Flag definitions self-heal - every minute. Drains the queue the Rust
    # /flags/definitions endpoint fills on cache miss and rebuilds those caches,
    # so a missing entry heals in ~1 min instead of waiting for the hourly verifier.
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        drain_flag_definitions_rebuild_requests.s(),
        name="drain flag definitions rebuild requests",
        expires_seconds=60,
    )

    # Feature flags local-eval canary - every 5 minutes
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/5"),
        feature_flags_local_eval_canary_task.s(),
        name="feature flags local-eval canary",
        expires_seconds=5 * 60,
    )

    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/5"),
        report_stuck_heatmap_screenshots.s(),
        name="report stuck heatmap screenshots",
        expires_seconds=5 * 60,
    )

    # Auth token cache verification - every 6 hours at minute 40
    # Verifies per-token auth cache entries against the database,
    # deleting stale entries that signal-based invalidation may have missed.
    add_periodic_task_with_expiry(
        sender,
        crontab(hour="*/6", minute="40"),
        verify_and_fix_auth_token_cache_task.s(),
        name="verify and fix auth token cache",
        # expires_seconds omitted — defaults to 1.5x interval (9 h) so the safety-net
        # task survives moderate worker downtime without being dropped.
    )

    add_periodic_task_with_expiry(
        sender,
        crontab(hour="*/6", minute="20"),
        sweep_web_analytics_achievement_team_tracks.s(),
        name="web analytics achievements team-track sweep",
    )

    # Update events table partitions twice a week
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri", hour="0", minute="0"),
        update_event_partitions.s(),  # check twice a week
    )

    # Send all instance usage to the Billing service
    sender.add_periodic_task(
        crontab(hour="3", minute="45"),
        send_org_usage_reports.s(),
        name="send instance usage report",
    )

    # Send usage reports for specific orgs with delayed data ingestion
    delayed_orgs = DELAYED_ORGS_EU if get_instance_region() == "EU" else DELAYED_ORGS_US
    if delayed_orgs:
        sender.add_periodic_task(
            crontab(hour="10", minute="00"),
            send_org_usage_reports.s(organization_ids=delayed_orgs),
            name="send delayed org usage reports",
        )

    # Send AI observability usage reports daily at 4:15 AM UTC
    sender.add_periodic_task(
        crontab(hour="4", minute="15"),
        send_ai_observability_usage_reports.s(),
        name="send llm analytics usage reports",
    )

    # Send HogFunctions daily digest at 9:30 AM UTC (good for US and EU)
    sender.add_periodic_task(
        crontab(hour="9", minute="30"),
        send_hog_functions_daily_digest.s(),
        name="send HogFunctions daily digest",
    )

    # Send Error Tracking weekly digest at 8:30 AM UTC on Monday
    sender.add_periodic_task(
        crontab(hour="8", minute="30", day_of_week="mon"),
        send_error_tracking_weekly_digest.s(),
        name="send Error Tracking weekly digest",
    )

    # Send materialized view failure digest daily at morning local time per region
    cloud_deployment = (settings.CLOUD_DEPLOYMENT or "").upper()
    if cloud_deployment == "EU":
        matview_digest_hour = "8"
    elif cloud_deployment == "US":
        matview_digest_hour = "14"
    else:
        matview_digest_hour = "9"

    sender.add_periodic_task(
        crontab(hour=matview_digest_hour, minute="0"),
        send_matview_failure_digest.s(),
        name="send matview failure digest",
    )

    # Just after the digest day rolls over (EXTERNAL_DATA_DIGEST_DAY_BOUNDARY_HOUR_UTC),
    # when the date-keyed campaign block resets.
    sender.add_periodic_task(
        crontab(hour=str(EXTERNAL_DATA_DIGEST_DAY_BOUNDARY_HOUR_UTC), minute="15"),
        send_external_data_failure_digest_catchup.s(),
        name="send external data failure digest catch-up",
    )

    # Every 30 minutes, send decide request counts to the main posthog instance
    sender.add_periodic_task(
        crontab(minute="*/30"),
        calculate_decide_usage.s(),
        name="calculate decide usage",
    )

    # Sync feature flag last_called_at timestamps from ClickHouse every 30 minutes
    sender.add_periodic_task(
        crontab(minute="*/30"),
        sync_feature_flag_last_called.s(),
        name="sync feature flag last_called_at timestamps",
        expires=1800,  # 30 minutes - prevents stale tasks from running
    )

    # Reset master project data every Monday at Thursday at 5 AM UTC. Mon and Thu because doing this every day
    # would be too hard on ClickHouse, and those days ensure most users will have data at most 3 days old.
    # sender.add_periodic_task(crontab(day_of_week="mon,thu", hour="5", minute="0"), demo_reset_master_team.s())

    sender.add_periodic_task(crontab(day_of_week="fri", hour="0", minute="0"), clean_stale_partials.s())

    # Clear expired Django sessions daily at 4 AM
    sender.add_periodic_task(
        crontab(hour="4", minute="0"),
        clear_expired_sessions.s(),
        name="clear expired sessions",
    )

    # Sync all Organization.available_product_features every hour, only for billing v1 orgs
    sender.add_periodic_task(crontab(minute="30", hour="*"), sync_all_organization_available_product_features.s())

    sender.add_periodic_task(crontab(minute="*/15"), check_async_migration_health.s())

    if settings.INGESTION_LAG_METRIC_TEAM_IDS:
        sender.add_periodic_task(60, ingestion_lag.s(), name="ingestion lag")

    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        clickhouse_row_count.s(),
        name="clickhouse events table row count",
    )
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        clickhouse_part_count.s(),
        name="clickhouse table parts count",
    )
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        clickhouse_mutation_count.s(),
        name="clickhouse table mutations count",
    )
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        clickhouse_errors_count.s(),
        name="clickhouse instance errors count",
    )

    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        pg_table_cache_hit_rate.s(),
        name="PG table cache hit rate",
    )
    sender.add_periodic_task(
        crontab(minute="0", hour="*"),
        pg_plugin_server_query_timing.s(),
        name="PG plugin server query timing",
    )

    sender.add_periodic_task(
        get_crontab(settings.CALCULATE_COHORTS_DAY_SCHEDULE),
        calculate_cohort.s(),
        name="recalculate cohorts day",
        expires=120 * 1.5,
        args=(settings.CALCULATE_X_PARALLEL_COHORTS_DURING_DAY,),
    )

    sender.add_periodic_task(
        get_crontab(settings.CALCULATE_COHORTS_NIGHT_SCHEDULE),
        calculate_cohort.s(),
        name="recalculate cohorts night",
        expires=60 * 1.5,
        args=(settings.CALCULATE_X_PARALLEL_COHORTS_DURING_NIGHT,),
    )

    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*/2"),
        process_scheduled_changes.s(),
        name="process scheduled changes",
    )

    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        process_due_reminders.s(),
        name="process due reminders",
    )

    if clear_clickhouse_crontab := get_crontab(settings.CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON):
        sender.add_periodic_task(
            clear_clickhouse_crontab,
            clickhouse_clear_removed_data.s(),
            name="clickhouse clear removed data",
        )

    if clear_clickhouse_deleted_person_crontab := get_crontab(settings.CLEAR_CLICKHOUSE_DELETED_PERSON_SCHEDULE_CRON):
        sender.add_periodic_task(
            clear_clickhouse_deleted_person_crontab,
            clear_clickhouse_deleted_person.s(),
            name="clickhouse clear deleted person data",
        )

    sender.add_periodic_task(
        crontab(hour="*", minute="0"),
        stop_surveys_reached_target.s(),
        name="stop surveys that reached responses limits",
    )

    sender.add_periodic_task(
        crontab(hour="*/12", minute="0"),
        refresh_activity_log_fields_cache.s(),
        name="refresh activity log fields cache for large orgs",
    )

    sender.add_periodic_task(
        crontab(hour="*/12"),
        update_survey_iteration.s(),
        name="update survey iteration based on date",
    )

    sender.add_periodic_task(
        crontab(hour="*/12"),
        update_survey_adaptive_sampling.s(),
        name="update survey's sampling feature flag rollout  based on date",
    )

    sender.add_periodic_task(
        crontab(hour="8", minute="15"),
        logs_alert_events_cleanup_task.s(),
        name="clean up old logs alert events",
    )

    if settings.EE_AVAILABLE:
        sender.add_periodic_task(
            crontab(hour="0", minute=str(randrange(0, 40))),
            clickhouse_send_license_usage.s(),
        )  # every day at a random minute past midnight. Randomize to avoid overloading license.posthog.com
        sender.add_periodic_task(
            crontab(hour="4", minute=str(randrange(0, 40))),
            clickhouse_send_license_usage.s(),
        )  # again a few hours later just to make sure

        materialize_columns_crontab = get_crontab(settings.MATERIALIZE_COLUMNS_SCHEDULE_CRON)

        if materialize_columns_crontab:
            sender.add_periodic_task(
                materialize_columns_crontab,
                clickhouse_materialize_columns.s(),
                name="clickhouse materialize columns",
            )

        sender.add_periodic_task(
            crontab(minute="0", hour="*"),
            check_flags_to_rollback.s(),
            name="check feature flags that should be rolled back",
        )

        sender.add_periodic_task(
            crontab(minute="10", hour="*/12"),
            find_flags_with_enriched_analytics.s(),
            name="find feature flags with enriched analytics",
        )

        sender.add_periodic_task(
            # once a day a random minute after midnight
            crontab(hour="0", minute=str(randrange(0, 40))),
            delete_expired_exported_assets.s(),
            name="delete expired exported assets",
        )

        # Daily cleanup of expired onboarding delegation invites. `pre_delete` re-enables
        # the delegator's onboarding, so a missed sweep strands delegators on the "waiting
        # for teammate" screen forever.
        sender.add_periodic_task(
            crontab(hour="1", minute=str(randrange(0, 40))),
            delete_expired_delegation_invites.s(),
            name="delete expired delegation invites",
        )

        from ee.tasks.scim_request_log_cleanup import cleanup_old_scim_request_logs

        add_periodic_task_with_expiry(
            sender,
            crontab(minute="0"),
            cleanup_old_scim_request_logs.s(),
            name="clean up old SCIM request logs",
        )

    # Check integrations to refresh every minute
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        refresh_integrations.s(),
        name="refresh integrations",
    )

    sender.add_periodic_task(
        crontab(hour="0", minute=str(randrange(0, 40))),
        sync_all_remote_configs.s(),
        name="sync all remote configs",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="*/5"),
        sync_js_snippet_manifest.s(),
        name="sync posthog-js snippet manifest",
    )

    sender.add_periodic_task(
        crontab(hour="0", minute=str(randrange(0, 40))),
        sync_all_surveys_cache.s(),
        name="sync all surveys cache",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="0"),
        validate_pending_change_requests.s(),
        name="validate pending change requests",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="5"),
        expire_old_change_requests.s(),
        name="expire old change requests",
    )

    # Deactivate endpoint materializations that haven't been used in 30+ days
    sender.add_periodic_task(
        crontab(hour="5", minute="0"),
        deactivate_stale_materializations.s(),
        name="deactivate stale endpoint materializations",
    )

    # Hard-delete expired test saved queries and their downstream objects
    sender.add_periodic_task(
        crontab(hour="3", minute="30"),
        cleanup_expired_test_saved_queries.s(),
        name="cleanup expired test saved queries",
    )

    # Refresh expiring OAuth tokens and re-sync stale tool catalogs for shared MCP installations
    sender.add_periodic_task(
        crontab(minute="45"),
        maintain_shared_installations.s(),
        name="maintain shared MCP installations",
    )

    # Reopen snoozed conversation tickets whose snooze period has expired
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        wake_snoozed_tickets.s(),
        name="wake snoozed conversation tickets",
    )

    # Re-drive queued outbound support email replies (survives a multi-day email provider outage)
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        flush_pending_email_replies.s(),
        name="flush pending conversation email replies",
    )

    # Pull ambient messages from MS Teams shared channels (which never push them
    # over the bot webhook) into the ticket pipeline via Graph messages/delta.
    add_periodic_task_with_expiry(
        sender,
        crontab(minute="*"),
        poll_teams_shared_channels.s(),
        name="poll teams shared channels",
    )
    # Delete expired Streamlit bridge OAuth tokens.
    sender.add_periodic_task(
        # Hourly because tokens have a 1-hour TTL and every connect_info
        # call mints a fresh one.
        crontab(hour="*", minute="55"),
        cleanup_expired_streamlit_oauth_tokens.s(),
        name="cleanup expired streamlit oauth tokens",
    )

    # Hard-delete S3 zips for Streamlit apps past their soft-delete retention.
    sender.add_periodic_task(
        crontab(hour="4", minute="10"),
        cleanup_deleted_streamlit_app_zips.s(),
        name="cleanup deleted streamlit app zips",
    )

    # Stop streamlit sandboxes left idle past their inactivity window.
    sender.add_periodic_task(
        crontab(minute="*/5"),
        stop_idle_streamlit_sandboxes.s(),
        name="stop idle streamlit sandboxes",
    )

    # Restart streamlit sandboxes that died on their own (Modal TTL timeout).
    sender.add_periodic_task(
        crontab(minute="*"),
        auto_restart_crashed_streamlit_sandboxes.s(),
        name="auto restart crashed streamlit sandboxes",
    )

    # Prune non-active streamlit app versions past their retention window.
    sender.add_periodic_task(
        crontab(hour="3", minute="0"),
        prune_old_streamlit_app_versions.s(),
        name="prune old streamlit app versions",
    )
