import os
import time
from random import randrange

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, task_postrun, task_prerun, worker_process_init
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_structlog.celery.steps import DjangoStructLogInitStep

from posthog.redis import get_client
from posthog.utils import get_crontab

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

app = Celery("posthog")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Make sure Redis doesn't add too many connections
# https://stackoverflow.com/questions/47106592/redis-connections-not-being-released-after-celery-task-is-complete
app.conf.broker_pool_limit = 0

app.steps["worker"].add(DjangoStructLogInitStep)

# How frequently do we want to calculate action -> event relationships if async is enabled
ACTION_EVENT_MAPPING_INTERVAL_SECONDS = settings.ACTION_EVENT_MAPPING_INTERVAL_SECONDS

# How frequently do we want to calculate event property stats if async is enabled
EVENT_PROPERTY_USAGE_INTERVAL_SECONDS = settings.EVENT_PROPERTY_USAGE_INTERVAL_SECONDS

# How frequently do we want to check if dashboard items need to be recalculated
UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS = settings.UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS


@setup_logging.connect
def receiver_setup_logging(loglevel, logfile, format, colorize, **kwargs) -> None:
    import logging

    from posthog.settings import logs

    # following instructions from here https://django-structlog.readthedocs.io/en/latest/celery.html
    # mypy thinks that there is no `logging.config` but there is ¯\_(ツ)_/¯
    logging.config.dictConfig(logs.LOGGING)  # type: ignore


@worker_process_init.connect
def on_worker_start(**kwargs) -> None:
    from posthog.settings import sentry_init

    sentry_init(traces_sample_rate=0.05)


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs):
    # Monitoring tasks
    sender.add_periodic_task(60.0, monitoring_check_clickhouse_schema_drift.s(), name="Monitor ClickHouse schema drift")

    if not settings.DEBUG:
        sender.add_periodic_task(1.0, redis_celery_queue_depth.s(), name="1 sec queue probe", priority=0)
    # Heartbeat every 10sec to make sure the worker is alive
    sender.add_periodic_task(10.0, redis_heartbeat.s(), name="10 sec heartbeat", priority=0)

    # Update events table partitions twice a week
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri", hour=0, minute=0), update_event_partitions.s(),  # check twice a week
    )

    # Send weekly status report on self-hosted instances
    if not getattr(settings, "MULTI_TENANCY", False):
        sender.add_periodic_task(crontab(day_of_week="mon", hour=0, minute=0), status_report.s())

    # Cloud (posthog-cloud) cron jobs
    if getattr(settings, "MULTI_TENANCY", False):
        sender.add_periodic_task(crontab(hour=0, minute=0), calculate_billing_daily_usage.s())  # every day midnight UTC
        sender.add_periodic_task(crontab(hour=4, minute=0), verify_persons_data_in_sync.s())

    sender.add_periodic_task(crontab(day_of_week="fri", hour=0, minute=0), clean_stale_partials.s())

    # Send the emails at 3PM UTC every day
    sender.add_periodic_task(crontab(hour=15, minute=0), send_first_ingestion_reminder_emails.s())
    sender.add_periodic_task(crontab(hour=15, minute=0), send_second_ingestion_reminder_emails.s())

    # sync all Organization.available_features every hour
    sender.add_periodic_task(crontab(minute=30, hour="*"), sync_all_organization_available_features.s())

    sender.add_periodic_task(
        UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS, check_cached_items.s(), name="check dashboard items"
    )

    sender.add_periodic_task(crontab(minute="*/15"), check_async_migration_health.s())

    if settings.INGESTION_LAG_METRIC_TEAM_IDS:
        sender.add_periodic_task(60, ingestion_lag.s(), name="ingestion lag")
    sender.add_periodic_task(120, clickhouse_lag.s(), name="clickhouse table lag")
    sender.add_periodic_task(120, clickhouse_row_count.s(), name="clickhouse events table row count")
    sender.add_periodic_task(120, clickhouse_part_count.s(), name="clickhouse table parts count")
    sender.add_periodic_task(120, clickhouse_mutation_count.s(), name="clickhouse table mutations count")

    sender.add_periodic_task(120, pg_table_cache_hit_rate.s(), name="PG table cache hit rate")
    sender.add_periodic_task(
        crontab(minute=0, hour="*"), pg_plugin_server_query_timing.s(), name="PG plugin server query timing"
    )

    sender.add_periodic_task(crontab(minute=0, hour="*"), calculate_cohort_ids_in_feature_flags_task.s())

    sender.add_periodic_task(120, calculate_cohort.s(), name="recalculate cohorts")

    if settings.ASYNC_EVENT_PROPERTY_USAGE:
        sender.add_periodic_task(
            EVENT_PROPERTY_USAGE_INTERVAL_SECONDS,
            calculate_event_property_usage.s(),
            name="calculate event property usage",
        )

    clear_clickhouse_crontab = get_crontab(settings.CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON)
    if clear_clickhouse_crontab:
        sender.add_periodic_task(
            clear_clickhouse_crontab, clickhouse_clear_removed_data.s(), name="clickhouse clear removed data"
        )

    if settings.EE_AVAILABLE:
        sender.add_periodic_task(
            crontab(
                hour=0, minute=randrange(0, 40)
            ),  # every day at a random minute past midnight. Sends data from the preceding whole day.
            send_org_usage_report.s(),
            name="send event usage report",
        )

        sender.add_periodic_task(
            crontab(hour=0, minute=randrange(0, 40)), clickhouse_send_license_usage.s()
        )  # every day at a random minute past midnight. Randomize to avoid overloading license.posthog.com

        materialize_columns_crontab = get_crontab(settings.MATERIALIZE_COLUMNS_SCHEDULE_CRON)

        if materialize_columns_crontab:
            sender.add_periodic_task(
                materialize_columns_crontab, clickhouse_materialize_columns.s(), name="clickhouse materialize columns",
            )

            sender.add_periodic_task(
                crontab(hour="*/4", minute=0),
                clickhouse_mark_all_materialized.s(),
                name="clickhouse mark all columns as materialized",
            )

        # Hourly check for email subscriptions
        sender.add_periodic_task(crontab(hour="*", minute=55), schedule_all_subscriptions.s())


# Set up clickhouse query instrumentation
@task_prerun.connect
def set_up_instrumentation(task_id, task, **kwargs):
    from posthog import client

    client._request_information = {"kind": "celery", "id": task.name}


@task_postrun.connect
def teardown_instrumentation(task_id, task, **kwargs):
    from posthog import client

    client._request_information = None


@app.task(ignore_result=True)
def redis_heartbeat():
    get_client().set("POSTHOG_HEARTBEAT", int(time.time()))


@app.task(ignore_result=True, bind=True)
def enqueue_clickhouse_execute_with_progress(
    self, team_id, query_id, query, args=None, settings=None, with_column_types=False
):
    """
    Kick off query with progress reporting
    Iterate over the progress status
    Save status to redis
    Once complete save results to redis
    """
    from posthog.client import execute_with_progress

    execute_with_progress(team_id, query_id, query, args, settings, with_column_types, task_id=self.request.id)


@app.task(ignore_result=True)
def pg_table_cache_hit_rate():
    from posthog.internal_metrics import gauge

    with connection.cursor() as cursor:
        try:
            cursor.execute(
                """
                SELECT
                 relname as table_name,
                 sum(heap_blks_hit) / nullif(sum(heap_blks_hit) + sum(heap_blks_read),0) * 100 AS ratio
                FROM pg_statio_user_tables
                GROUP BY relname
                ORDER BY ratio ASC
            """
            )
            tables = cursor.fetchall()
            for row in tables:
                gauge("pg_table_cache_hit_rate", float(row[1]), tags={"table": row[0]})
        except:
            # if this doesn't work keep going
            pass


@app.task(ignore_result=True)
def pg_plugin_server_query_timing():
    from posthog.internal_metrics import gauge

    with connection.cursor() as cursor:
        try:
            cursor.execute(
                """
                SELECT
                    substring(query from 'plugin-server:(\\w+)') AS query_type,
                    total_time as total_time,
                    (total_time / calls) as avg_time,
                    min_time,
                    max_time,
                    stddev_time,
                    calls,
                    rows as rows_read_or_affected
                FROM pg_stat_statements
                WHERE query LIKE '%%plugin-server%%'
                ORDER BY total_time DESC
                LIMIT 50
                """
            )

            for row in cursor.fetchall():
                row_dictionary = {column.name: value for column, value in zip(cursor.description, row)}

                for key, value in row_dictionary.items():
                    if key == "query_type":
                        continue
                    gauge(f"pg_plugin_server_query_{key}", value, tags={"query_type": row_dictionary["query_type"]})
        except:
            # if this doesn't work keep going
            pass


CLICKHOUSE_TABLES = [
    "events",
    "person",
    "person_distinct_id",
    "person_distinct_id2",
    "session_recording_events",
]

if settings.CLICKHOUSE_REPLICATION:
    CLICKHOUSE_TABLES.extend(
        ["sharded_events", "sharded_session_recording_events",]
    )


@app.task(ignore_result=True)
def clickhouse_lag():
    from posthog.client import sync_execute
    from posthog.internal_metrics import gauge

    for table in CLICKHOUSE_TABLES:
        try:
            QUERY = """select max(_timestamp) observed_ts, now() now_ts, now() - max(_timestamp) as lag from {table};"""
            query = QUERY.format(table=table)
            lag = sync_execute(query)[0][2]
            gauge("posthog_celery_clickhouse__table_lag_seconds", lag, tags={"table": table})
        except:
            pass


HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC = {
    "heartbeat": "ingestion",
    "heartbeat_buffer": "ingestion_buffer",
    "heartbeat_api": "ingestion_api",
}


@app.task(ignore_result=True)
def ingestion_lag():
    from posthog.client import sync_execute
    from posthog.internal_metrics import gauge

    # Requires https://github.com/PostHog/posthog-heartbeat-plugin to be enabled on team 2
    # Note that it runs every minute and we compare it with now(), so there's up to 60s delay
    for event, metric in HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC.items():
        try:
            query = """
                SELECT now() - max(parseDateTimeBestEffortOrNull(JSONExtractString(properties, '$timestamp')))
                FROM events WHERE team_id IN %(team_ids)s AND _timestamp > yesterday() AND event = %(event)s;"""
            lag = sync_execute(query, {"team_ids": settings.INGESTION_LAG_METRIC_TEAM_IDS, "event": event})[0][0]
            gauge(f"posthog_celery_{metric}_lag_seconds_rough_minute_precision", lag)
        except:
            pass


@app.task(ignore_result=True)
def clickhouse_row_count():
    from posthog.client import sync_execute
    from posthog.internal_metrics import gauge

    for table in CLICKHOUSE_TABLES:
        try:
            QUERY = """select count(1) freq from {table};"""
            query = QUERY.format(table=table)
            rows = sync_execute(query)[0][0]
            gauge(f"posthog_celery_clickhouse_table_row_count", rows, tags={"table": table})
        except:
            pass


@app.task(ignore_result=True)
def clickhouse_part_count():
    from posthog.client import sync_execute
    from posthog.internal_metrics import gauge

    QUERY = """
        select table, count(1) freq
        from system.parts
        group by table
        order by freq desc;
    """
    rows = sync_execute(QUERY)
    for (table, parts) in rows:
        gauge(f"posthog_celery_clickhouse_table_parts_count", parts, tags={"table": table})


@app.task(ignore_result=True)
def clickhouse_mutation_count():
    from posthog.client import sync_execute
    from posthog.internal_metrics import gauge

    QUERY = """
        SELECT
            table,
            count(1) AS freq
        FROM system.mutations
        WHERE is_done = 0
        GROUP BY table
        ORDER BY freq DESC
    """
    rows = sync_execute(QUERY)
    for (table, muts) in rows:
        gauge(f"posthog_celery_clickhouse_table_mutations_count", muts, tags={"table": table})


@app.task(ignore_result=True)
def clickhouse_clear_removed_data():
    from posthog.models.team.util import delete_clickhouse_data_for_deleted_teams

    delete_clickhouse_data_for_deleted_teams()


@app.task(ignore_result=True)
def redis_celery_queue_depth():
    from posthog.internal_metrics import gauge

    try:
        llen = get_client().llen("celery")
        gauge(f"posthog_celery_queue_depth", llen)
    except:
        # if we can't connect to statsd don't complain about it.
        # not every installation will have statsd available
        return


@app.task(ignore_result=True)
def update_event_partitions():
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = 'update_partitions')) THEN PERFORM update_partitions(); END IF; END $$"
        )


@app.task(ignore_result=True)
def clean_stale_partials():
    """Clean stale (meaning older than 7 days) partial social auth sessions."""
    from social_django.models import Partial

    Partial.objects.filter(timestamp__lt=timezone.now() - timezone.timedelta(7)).delete()


@app.task(ignore_result=True)
def status_report():
    from posthog.tasks.status_report import status_report

    status_report()


@app.task(ignore_result=True)
def monitoring_check_clickhouse_schema_drift():
    from posthog.tasks.check_clickhouse_schema_drift import check_clickhouse_schema_drift

    check_clickhouse_schema_drift()


@app.task(ignore_result=True)
def calculate_cohort():
    from posthog.tasks.calculate_cohort import calculate_cohorts

    calculate_cohorts()


@app.task(ignore_result=True)
def check_cached_items():
    from posthog.tasks.update_cache import update_cached_items

    update_cached_items()


@app.task(ignore_result=True)
def update_cache_item_task(key: str, cache_type, payload: dict) -> None:
    from posthog.tasks.update_cache import update_cache_item

    update_cache_item(key, cache_type, payload)


@app.task(ignore_result=True)
def calculate_cohort_ids_in_feature_flags_task():
    from posthog.tasks.cohorts_in_feature_flag import calculate_cohort_ids_in_feature_flags

    calculate_cohort_ids_in_feature_flags()


@app.task(ignore_result=True, bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")


@app.task(ignore_result=True)
def calculate_event_property_usage():
    from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage

    calculate_event_property_usage()


@app.task(ignore_result=True)
def calculate_billing_daily_usage():
    try:
        from multi_tenancy.tasks import compute_daily_usage_for_organizations  # noqa: F401
    except ImportError:
        pass
    else:
        compute_daily_usage_for_organizations()


@app.task(ignore_result=True)
def send_first_ingestion_reminder_emails():
    from posthog.tasks.email import send_first_ingestion_reminder_emails

    send_first_ingestion_reminder_emails()


@app.task(ignore_result=True)
def send_second_ingestion_reminder_emails():
    from posthog.tasks.email import send_second_ingestion_reminder_emails

    send_second_ingestion_reminder_emails()


@app.task(ignore_result=True)
def sync_all_organization_available_features():
    from posthog.tasks.sync_all_organization_available_features import sync_all_organization_available_features

    sync_all_organization_available_features()


@app.task(ignore_result=False, track_started=True, max_retries=0)
def check_async_migration_health():
    from posthog.tasks.async_migrations import check_async_migration_health

    check_async_migration_health()


@app.task(ignore_result=True)
def verify_persons_data_in_sync():
    from posthog.tasks.verify_persons_data_in_sync import verify_persons_data_in_sync as verify

    verify()


def recompute_materialized_columns_enabled() -> bool:
    from posthog.models.instance_setting import get_instance_setting

    if get_instance_setting("MATERIALIZED_COLUMNS_ENABLED") and get_instance_setting(
        "COMPUTE_MATERIALIZED_COLUMNS_ENABLED"
    ):
        return True
    return False


@app.task(ignore_result=True)
def clickhouse_materialize_columns():
    if recompute_materialized_columns_enabled():
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize_properties_task
        except ImportError:
            pass
        else:
            materialize_properties_task()


@app.task(ignore_result=True)
def clickhouse_mark_all_materialized():
    if recompute_materialized_columns_enabled():
        try:
            from ee.tasks.materialized_columns import mark_all_materialized
        except ImportError:
            pass
        else:
            mark_all_materialized()


@app.task(ignore_result=True)
def clickhouse_send_license_usage():
    try:
        if not settings.MULTI_TENANCY:
            from ee.tasks.send_license_usage import send_license_usage

            send_license_usage()
    except ImportError:
        pass


@app.task(ignore_result=True)
def send_org_usage_report():
    try:
        from ee.tasks.org_usage_report import send_all_org_usage_reports
    except ImportError:
        pass
    else:
        send_all_org_usage_reports()


@app.task(ignore_result=True)
def schedule_all_subscriptions():
    try:
        from ee.tasks.subscriptions import schedule_all_subscriptions as _schedule_all_subscriptions
    except ImportError:
        pass
    else:
        _schedule_all_subscriptions()
