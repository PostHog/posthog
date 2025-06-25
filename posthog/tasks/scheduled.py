from random import randrange
from typing import Any

from celery import Celery
from celery.canvas import Signature
from celery.schedules import crontab
from django.conf import settings

from posthog.caching.warming import schedule_warming_for_teams_task
from posthog.tasks.alerts.checks import (
    alerts_backlog_task,
    check_alerts_task,
    checks_cleanup_task,
    reset_stuck_alerts_task,
)
from posthog.tasks.integrations import refresh_integrations
from posthog.tasks.periodic_digest.periodic_digest import send_all_periodic_digest_reports
from posthog.tasks.tasks import (
    calculate_cohort,
    calculate_decide_usage,
    check_async_migration_health,
    check_flags_to_rollback,
    clean_stale_partials,
    clear_clickhouse_deleted_person,
    clickhouse_clear_removed_data,
    clickhouse_errors_count,
    clickhouse_mark_all_materialized,
    clickhouse_materialize_columns,
    clickhouse_mutation_count,
    clickhouse_part_count,
    clickhouse_row_count,
    clickhouse_send_license_usage,
    delete_expired_exported_assets,
    ee_persist_finished_recordings,
    ee_persist_finished_recordings_v2,
    find_flags_with_enriched_analytics,
    ingestion_lag,
    pg_plugin_server_query_timing,
    pg_row_count,
    pg_table_cache_hit_rate,
    process_scheduled_changes,
    redis_celery_queue_depth,
    redis_heartbeat,
    replay_count_metrics,
    send_org_usage_reports,
    start_poll_query_performance,
    stop_surveys_reached_target,
    sync_all_organization_available_product_features,
    update_event_partitions,
    update_survey_adaptive_sampling,
    update_survey_iteration,
    verify_persons_data_in_sync,
    count_items_in_playlists,
    schedule_all_subscriptions,
)
from posthog.utils import get_crontab

from posthog.tasks.remote_config import sync_all_remote_configs

TWENTY_FOUR_HOURS = 24 * 60 * 60


def add_periodic_task_with_expiry(
    sender: Celery,
    schedule_seconds: int,
    task_signature: Signature,
    name: str | None = None,
) -> None:
    """
    If the workers get delayed in processing tasks, then tasks that fire every X seconds get queued multiple times
    And so, are processed multiple times. But they often only need to be processed once.
    This schedules them with an expiry so that they aren't processed multiple times.
    The expiry is larger than the schedule so that if the worker is only slightly delayed, it still gets processed.
    """
    sender.add_periodic_task(
        schedule_seconds,
        task_signature,
        name=name,
        # we don't want to run multiple of these if the workers build up a backlog
        expires=schedule_seconds * 1.5,
    )


def setup_periodic_tasks(sender: Celery, **kwargs: Any) -> None:
    if not settings.DEBUG:
        add_periodic_task_with_expiry(sender, 10, redis_celery_queue_depth.s(), "10 sec queue probe")

    # Heartbeat every 10sec to make sure the worker is alive
    add_periodic_task_with_expiry(sender, 10, redis_heartbeat.s(), "10 sec heartbeat")

    add_periodic_task_with_expiry(sender, 20, start_poll_query_performance.s(), "20 sec query performance heartbeat")

    sender.add_periodic_task(
        crontab(hour="*", minute="0"),
        schedule_warming_for_teams_task.s(),
        name="schedule warming for largest teams",
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

    # Send all periodic digest reports
    sender.add_periodic_task(
        crontab(hour="9", minute="0", day_of_week="mon"),
        send_all_periodic_digest_reports.s(),
        name="send all weekly digest reports",
    )

    # PostHog Cloud cron jobs
    # NOTE: We can't use is_cloud here as some Django elements aren't loaded yet. We check in the task execution instead
    # Verify that persons data is in sync every day at 4 AM UTC
    sender.add_periodic_task(crontab(hour="4", minute="0"), verify_persons_data_in_sync.s())

    # Every 30 minutes, send decide request counts to the main posthog instance
    sender.add_periodic_task(
        crontab(minute="*/30"),
        calculate_decide_usage.s(),
        name="calculate decide usage",
    )

    # Reset master project data every Monday at Thursday at 5 AM UTC. Mon and Thu because doing this every day
    # would be too hard on ClickHouse, and those days ensure most users will have data at most 3 days old.
    # sender.add_periodic_task(crontab(day_of_week="mon,thu", hour="5", minute="0"), demo_reset_master_team.s())

    sender.add_periodic_task(crontab(day_of_week="fri", hour="0", minute="0"), clean_stale_partials.s())

    # Sync all Organization.available_product_features every hour, only for billing v1 orgs
    sender.add_periodic_task(crontab(minute="30", hour="*"), sync_all_organization_available_product_features.s())

    sender.add_periodic_task(crontab(minute="*/15"), check_async_migration_health.s())

    if settings.INGESTION_LAG_METRIC_TEAM_IDS:
        sender.add_periodic_task(60, ingestion_lag.s(), name="ingestion lag")

    add_periodic_task_with_expiry(
        sender,
        120,
        clickhouse_row_count.s(),
        name="clickhouse events table row count",
    )
    add_periodic_task_with_expiry(
        sender,
        120,
        clickhouse_part_count.s(),
        name="clickhouse table parts count",
    )
    add_periodic_task_with_expiry(
        sender,
        120,
        clickhouse_mutation_count.s(),
        name="clickhouse table mutations count",
    )
    add_periodic_task_with_expiry(
        sender,
        120,
        clickhouse_errors_count.s(),
        name="clickhouse instance errors count",
    )

    add_periodic_task_with_expiry(
        sender,
        120,
        pg_row_count.s(),
        name="PG tables row counts",
    )
    add_periodic_task_with_expiry(
        sender,
        120,
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
        120,
        process_scheduled_changes.s(),
        name="process scheduled changes",
    )

    add_periodic_task_with_expiry(sender, 3600, replay_count_metrics.s(), name="replay_count_metrics")

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
        crontab(hour="*/12"),
        stop_surveys_reached_target.s(),
        name="stop surveys that reached responses limits",
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
        crontab(hour="*", minute="*/2"),
        check_alerts_task.s(),
        name="check_alerts_task",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="*/12"),
        alerts_backlog_task.s(),
        name="alerts_backlog_task",
    )

    sender.add_periodic_task(
        crontab(hour="*", minute="*/15"),
        reset_stuck_alerts_task.s(),
        name="reset_stuck_alerts_task",
    )

    sender.add_periodic_task(
        crontab(hour="8", minute="0"),
        checks_cleanup_task.s(),
        name="clean up old alert checks",
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
                crontab(hour="*/4", minute="0"),
                clickhouse_mark_all_materialized.s(),
                name="clickhouse mark all columns as materialized",
            )

        sender.add_periodic_task(crontab(hour="*", minute="55"), schedule_all_subscriptions.s())

        sender.add_periodic_task(
            crontab(hour="2", minute=str(randrange(0, 40))),
            ee_persist_finished_recordings.s(),
            name="persist finished recordings",
        )
        sender.add_periodic_task(
            crontab(hour="2", minute=str(randrange(0, 40))),
            ee_persist_finished_recordings_v2.s(),
            name="persist finished recordings v2",
        )

        add_periodic_task_with_expiry(
            sender,
            settings.PLAYLIST_COUNTER_PROCESSING_SCHEDULE_SECONDS or TWENTY_FOUR_HOURS,
            count_items_in_playlists.s(),
            "ee_count_items_in_playlists",
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

    # Check integrations to refresh every minute
    add_periodic_task_with_expiry(
        sender,
        60,
        refresh_integrations.s(),
        name="refresh integrations",
    )

    sender.add_periodic_task(
        crontab(hour="0", minute=str(randrange(0, 40))),
        sync_all_remote_configs.s(),
        name="sync all remote configs",
    )
