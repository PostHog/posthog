import os
import time
from random import randrange
from typing import Optional
from uuid import UUID

from celery import Celery
from celery.canvas import Signature
from celery.schedules import crontab
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    task_success,
    worker_process_init,
)
from django.conf import settings
from django.db import connection
from django.dispatch import receiver
from django.utils import timezone
from django_structlog.celery import signals
from django_structlog.celery.steps import DjangoStructLogInitStep
from prometheus_client import Counter, Gauge

from posthog.cloud_utils import is_cloud
from posthog.metrics import pushed_metrics_registry
from posthog.ph_client import get_ph_client
from posthog.redis import get_client
from posthog.utils import get_crontab

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

app = Celery("posthog")

CELERY_TASK_PRE_RUN_COUNTER = Counter(
    "posthog_celery_task_pre_run",
    "task prerun signal is dispatched before a task is executed.",
    labelnames=["task_name"],
)

CELERY_TASK_SUCCESS_COUNTER = Counter(
    "posthog_celery_task_success",
    "task success signal is dispatched when a task succeeds.",
    labelnames=["task_name"],
)

CELERY_TASK_FAILURE_COUNTER = Counter(
    "posthog_celery_task_failure",
    "task failure signal is dispatched when a task succeeds.",
    labelnames=["task_name"],
)

CELERY_TASK_RETRY_COUNTER = Counter(
    "posthog_celery_task_retry",
    "task retry signal is dispatched when a task will be retried.",
    labelnames=["task_name"],
)

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


@setup_logging.connect
def receiver_setup_logging(loglevel, logfile, format, colorize, **kwargs) -> None:
    import logging

    from posthog.settings import logs

    # following instructions from here https://django-structlog.readthedocs.io/en/latest/celery.html
    # mypy thinks that there is no `logging.config` but there is ¯\_(ツ)_/¯
    logging.config.dictConfig(logs.LOGGING)  # type: ignore


@receiver(signals.bind_extra_task_metadata)
def receiver_bind_extra_request_metadata(sender, signal, task=None, logger=None):
    import structlog

    if task:
        structlog.contextvars.bind_contextvars(task_name=task.name)


@worker_process_init.connect
def on_worker_start(**kwargs) -> None:
    from prometheus_client import start_http_server

    from posthog.settings import sentry_init

    sentry_init()
    start_http_server(int(os.getenv("CELERY_METRICS_PORT", "8001")))


def add_periodic_task_with_expiry(
    sender: Celery,
    schedule_seconds: int,
    task_signature: Signature,
    name: str | None = None,
):
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


@app.on_after_configure.connect
def setup_periodic_tasks(sender: Celery, **kwargs):
    # Monitoring tasks
    add_periodic_task_with_expiry(
        sender,
        60,
        monitoring_check_clickhouse_schema_drift.s(),
        "check clickhouse schema drift",
    )

    if not settings.DEBUG:
        add_periodic_task_with_expiry(sender, 10, redis_celery_queue_depth.s(), "10 sec queue probe")

    # Heartbeat every 10sec to make sure the worker is alive
    add_periodic_task_with_expiry(sender, 10, redis_heartbeat.s(), "10 sec heartbeat")

    # Update events table partitions twice a week
    sender.add_periodic_task(
        crontab(day_of_week="mon,fri", hour="0", minute="0"),
        update_event_partitions.s(),  # check twice a week
    )

    # Send all instance usage to the Billing service
    # Sends later on Sunday due to clickhouse things that happen on Sunday at ~00:00 UTC
    sender.add_periodic_task(
        crontab(hour="2", minute="15", day_of_week="mon"),
        send_org_usage_reports.s(),
        name="send instance usage report",
    )
    sender.add_periodic_task(
        crontab(hour="0", minute="15", day_of_week="tue,wed,thu,fri,sat,sun"),
        send_org_usage_reports.s(),
        name="send instance usage report",
    )

    # Update local usage info for rate limiting purposes - offset by 30 minutes to not clash with the above
    sender.add_periodic_task(
        crontab(hour="*", minute="30"),
        update_quota_limiting.s(),
        name="update quota limiting",
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
    sender.add_periodic_task(crontab(day_of_week="mon,thu", hour="5", minute="0"), demo_reset_master_team.s())

    sender.add_periodic_task(crontab(day_of_week="fri", hour="0", minute="0"), clean_stale_partials.s())

    # Sync all Organization.available_features every hour, only for billing v1 orgs
    sender.add_periodic_task(crontab(minute="30", hour="*"), sync_all_organization_available_features.s())

    sync_insight_cache_states_schedule = get_crontab(settings.SYNC_INSIGHT_CACHE_STATES_SCHEDULE)
    if sync_insight_cache_states_schedule:
        sender.add_periodic_task(
            sync_insight_cache_states_schedule,
            sync_insight_cache_states_task.s(),
            name="sync insight cache states",
        )

    add_periodic_task_with_expiry(
        sender,
        settings.UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS,
        schedule_cache_updates_task.s(),
        "check dashboard items",
    )

    sender.add_periodic_task(crontab(minute="*/15"), check_async_migration_health.s())

    if settings.INGESTION_LAG_METRIC_TEAM_IDS:
        sender.add_periodic_task(60, ingestion_lag.s(), name="ingestion lag")

    add_periodic_task_with_expiry(
        sender,
        120,
        clickhouse_lag.s(),
        name="clickhouse table lag",
    )

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
    add_periodic_task_with_expiry(
        sender,
        60,
        graphile_worker_queue_size.s(),
        name="Graphile Worker queue size",
    )

    add_periodic_task_with_expiry(
        sender,
        120,
        calculate_cohort.s(),
        name="recalculate cohorts",
    )

    add_periodic_task_with_expiry(
        sender,
        120,
        process_scheduled_changes.s(),
        name="process scheduled changes",
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

    sender.add_periodic_task(
        crontab(minute="*/10"),
        sync_datawarehouse_sources.s(),
        name="sync datawarehouse sources that have settled in s3 bucket",
    )

    # Every 30 minutes try to retrieve and calculate total rows synced in period
    sender.add_periodic_task(
        crontab(minute="*/30"),
        calculate_external_data_rows_synced.s(),
        name="calculate external data rows synced",
    )


# Set up clickhouse query instrumentation
@task_prerun.connect
def pre_run_signal_handler(task_id, task, **kwargs):
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client.connection import (
        Workload,
        set_default_clickhouse_workload_type,
    )
    from posthog.clickhouse.query_tagging import tag_queries

    statsd.incr("celery_tasks_metrics.pre_run", tags={"name": task.name})
    tag_queries(kind="celery", id=task.name)
    set_default_clickhouse_workload_type(Workload.OFFLINE)

    CELERY_TASK_PRE_RUN_COUNTER.labels(task_name=task.name).inc()


@task_success.connect
def success_signal_handler(sender, **kwargs):
    CELERY_TASK_SUCCESS_COUNTER.labels(task_name=sender.name).inc()


@task_failure.connect
def failure_signal_handler(sender, **kwargs):
    CELERY_TASK_FAILURE_COUNTER.labels(task_name=sender.name).inc()


@task_retry.connect
def retry_signal_handler(sender, **kwargs):
    CELERY_TASK_RETRY_COUNTER.labels(task_name=sender.name).inc()


@task_postrun.connect
def teardown_instrumentation(task_id, task, **kwargs):
    from posthog.clickhouse.query_tagging import reset_query_tags

    reset_query_tags()


@app.task(ignore_result=True)
def delete_expired_exported_assets() -> None:
    from posthog.models import ExportedAsset

    ExportedAsset.delete_expired_assets()


@app.task(ignore_result=True)
def redis_heartbeat():
    get_client().set("POSTHOG_HEARTBEAT", int(time.time()))


@app.task(ignore_result=True, bind=True)
def process_query_task(self, team_id, query_id, query_json, limit_context=None, refresh_requested=False):
    """
    Kick off query
    Once complete save results to redis
    """
    from posthog.client import execute_process_query

    execute_process_query(
        team_id=team_id,
        query_id=query_id,
        query_json=query_json,
        limit_context=limit_context,
        refresh_requested=refresh_requested,
    )


@app.task(ignore_result=True)
def pg_table_cache_hit_rate():
    from statshog.defaults.django import statsd

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
            with pushed_metrics_registry("celery_pg_table_cache_hit_rate") as registry:
                hit_rate_gauge = Gauge(
                    "posthog_celery_pg_table_cache_hit_rate",
                    "Postgres query cache hit rate per table.",
                    labelnames=["table_name"],
                    registry=registry,
                )
                for row in tables:
                    hit_rate_gauge.labels(table_name=row[0]).set(float(row[1]))
                    statsd.gauge("pg_table_cache_hit_rate", float(row[1]), tags={"table": row[0]})
        except:
            # if this doesn't work keep going
            pass


@app.task(ignore_result=True)
def pg_plugin_server_query_timing():
    from statshog.defaults.django import statsd

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
                    statsd.gauge(
                        f"pg_plugin_server_query_{key}",
                        value,
                        tags={"query_type": row_dictionary["query_type"]},
                    )
        except:
            # if this doesn't work keep going
            pass


POSTGRES_TABLES = ["posthog_personoverride", "posthog_personoverridemapping"]


@app.task(ignore_result=True)
def pg_row_count():
    with pushed_metrics_registry("celery_pg_row_count") as registry:
        row_count_gauge = Gauge(
            "posthog_celery_pg_table_row_count",
            "Number of rows per Postgres table.",
            labelnames=["table_name"],
            registry=registry,
        )
        with connection.cursor() as cursor:
            for table in POSTGRES_TABLES:
                QUERY = "SELECT count(*) FROM {table};"
                query = QUERY.format(table=table)

                try:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    row_count_gauge.labels(table_name=table).set(row[0])
                except:
                    pass


CLICKHOUSE_TABLES = [
    "sharded_events",
    "person",
    "person_distinct_id2",
    "sharded_session_replay_events",
    "log_entries",
]
if not is_cloud():
    CLICKHOUSE_TABLES.append("session_recording_events")


@app.task(ignore_result=True)
def clickhouse_lag():
    from statshog.defaults.django import statsd

    from posthog.client import sync_execute

    with pushed_metrics_registry("celery_clickhouse_lag") as registry:
        lag_gauge = Gauge(
            "posthog_celery_clickhouse_lag_seconds",
            "Age of the latest ingested record per ClickHouse table.",
            labelnames=["table_name"],
            registry=registry,
        )
        for table in CLICKHOUSE_TABLES:
            try:
                QUERY = """SELECT max(_timestamp) observed_ts, now() now_ts, now() - max(_timestamp) as lag
                    FROM {table}"""
                query = QUERY.format(table=table)
                lag = sync_execute(query)[0][2]
                statsd.gauge(
                    "posthog_celery_clickhouse__table_lag_seconds",
                    lag,
                    tags={"table": table},
                )
                lag_gauge.labels(table_name=table).set(lag)
            except:
                pass


HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC = {
    "heartbeat": "ingestion",
    "heartbeat_buffer": "ingestion_buffer",
    "heartbeat_api": "ingestion_api",
}


@app.task(ignore_result=True)
def ingestion_lag():
    from statshog.defaults.django import statsd

    from posthog.client import sync_execute

    # Requires https://github.com/PostHog/posthog-heartbeat-plugin to be enabled on team 2
    # Note that it runs every minute, and we compare it with now(), so there's up to 60s delay
    query = """
    SELECT event, date_diff('second', max(timestamp), now())
    FROM events
    WHERE team_id IN %(team_ids)s
        AND event IN %(events)s
        AND timestamp > yesterday() AND timestamp < now() + toIntervalMinute(3)
    GROUP BY event
    """

    try:
        results = sync_execute(
            query,
            {
                "team_ids": settings.INGESTION_LAG_METRIC_TEAM_IDS,
                "events": list(HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC.keys()),
            },
        )
        with pushed_metrics_registry("celery_ingestion_lag") as registry:
            lag_gauge = Gauge(
                "posthog_celery_observed_ingestion_lag_seconds",
                "End-to-end ingestion lag observed through several scenarios. Can be overestimated by up to 60 seconds.",
                labelnames=["scenario"],
                registry=registry,
            )
            for event, lag in results:
                metric = HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC[event]
                statsd.gauge(f"posthog_celery_{metric}_lag_seconds_rough_minute_precision", lag)
                lag_gauge.labels(scenario=metric).set(lag)
    except:
        pass


KNOWN_CELERY_TASK_IDENTIFIERS = {
    "pluginJob",
    "runEveryHour",
    "runEveryMinute",
    "runEveryDay",
}


@app.task(ignore_result=True)
def graphile_worker_queue_size():
    from django.db import connections
    from statshog.defaults.django import statsd

    connection = connections["graphile"] if "graphile" in connections else connections["default"]
    with connection.cursor() as cursor:
        cursor.execute(
            """
        SELECT count(*)
        FROM graphile_worker.jobs
        WHERE (jobs.locked_at is null or jobs.locked_at < (now() - INTERVAL '4 hours'))
        AND run_at <= now()
        AND attempts < max_attempts
        """
        )

        queue_size = cursor.fetchone()[0]
        statsd.gauge("graphile_worker_queue_size", queue_size)

        # Track the number of jobs that will still be run at least once or are currently running based on job type (i.e. task_identifier)
        # Completed jobs are deleted and "permanently failed" jobs have attempts == max_attempts
        # Jobs not yet eligible for execution are filtered out with run_at <= now()
        cursor.execute(
            """
        SELECT task_identifier, count(*) as c, EXTRACT(EPOCH FROM MIN(run_at)) as oldest FROM graphile_worker.jobs
        WHERE attempts < max_attempts
        AND run_at <= now()
        GROUP BY task_identifier
        """
        )

        seen_task_identifier = set()
        with pushed_metrics_registry("celery_graphile_worker_queue_size") as registry:
            processing_lag_gauge = Gauge(
                "posthog_celery_graphile_lag_seconds",
                "Oldest scheduled run on pending Graphile jobs per task identifier, zero if queue empty.",
                labelnames=["task_identifier"],
                registry=registry,
            )
            waiting_jobs_gauge = Gauge(
                "posthog_celery_graphile_waiting_jobs",
                "Number of Graphile jobs in the queue, per task identifier.",
                labelnames=["task_identifier"],
                registry=registry,
            )
            for task_identifier, count, oldest in cursor.fetchall():
                seen_task_identifier.add(task_identifier)
                waiting_jobs_gauge.labels(task_identifier=task_identifier).set(count)
                processing_lag_gauge.labels(task_identifier=task_identifier).set(time.time() - float(oldest))
                statsd.gauge(
                    "graphile_waiting_jobs",
                    count,
                    tags={"task_identifier": task_identifier},
                )

            # The query will not return rows for empty queues, creating missing points.
            # Let's emit updates for known queues even if they are empty.
            for task_identifier in KNOWN_CELERY_TASK_IDENTIFIERS - seen_task_identifier:
                waiting_jobs_gauge.labels(task_identifier=task_identifier).set(0)
                processing_lag_gauge.labels(task_identifier=task_identifier).set(0)


@app.task(ignore_result=True)
def clickhouse_row_count():
    from statshog.defaults.django import statsd

    from posthog.client import sync_execute

    with pushed_metrics_registry("celery_clickhouse_row_count") as registry:
        row_count_gauge = Gauge(
            "posthog_celery_clickhouse_table_row_count",
            "Number of rows per ClickHouse table.",
            labelnames=["table_name"],
            registry=registry,
        )
        for table in CLICKHOUSE_TABLES:
            try:
                QUERY = """SELECT sum(rows) rows from system.parts
                       WHERE table = '{table}' and active;"""
                query = QUERY.format(table=table)
                rows = sync_execute(query)[0][0]
                row_count_gauge.labels(table_name=table).set(rows)
                statsd.gauge(
                    f"posthog_celery_clickhouse_table_row_count",
                    rows,
                    tags={"table": table},
                )
            except:
                pass


@app.task(ignore_result=True)
def clickhouse_errors_count():
    """
    This task is used to track the recency of errors in ClickHouse.
    We can use this to alert on errors that are consistently being generated recently
    999 - KEEPER_EXCEPTION
    225 - NO_ZOOKEEPER
    242 - TABLE_IS_READ_ONLY
    """
    from posthog.client import sync_execute

    QUERY = """
        select
            getMacro('replica') replica,
            getMacro('shard') shard,
            name,
            value as errors,
            dateDiff('minute', last_error_time, now()) minutes_ago
        from clusterAllReplicas('posthog', system, errors)
        where code in (999, 225, 242)
        order by minutes_ago
    """
    rows = sync_execute(QUERY)
    with pushed_metrics_registry("celery_clickhouse_errors") as registry:
        errors_gauge = Gauge(
            "posthog_celery_clickhouse_errors",
            "Age of the latest error per ClickHouse errors table.",
            registry=registry,
            labelnames=["replica", "shard", "name"],
        )
        if isinstance(rows, list):
            for replica, shard, name, _, minutes_ago in rows:
                errors_gauge.labels(replica=replica, shard=shard, name=name).set(minutes_ago)


@app.task(ignore_result=True)
def clickhouse_part_count():
    from statshog.defaults.django import statsd

    from posthog.client import sync_execute

    QUERY = """
        SELECT table, count(1) freq
        FROM system.parts
        WHERE active
        GROUP BY table
        ORDER BY freq DESC;
    """
    rows = sync_execute(QUERY)

    with pushed_metrics_registry("celery_clickhouse_part_count") as registry:
        parts_count_gauge = Gauge(
            "posthog_celery_clickhouse_table_parts_count",
            "Number of parts per ClickHouse table.",
            labelnames=["table"],
            registry=registry,
        )
        for table, parts in rows:
            parts_count_gauge.labels(table=table).set(parts)
            statsd.gauge(
                f"posthog_celery_clickhouse_table_parts_count",
                parts,
                tags={"table": table},
            )


@app.task(ignore_result=True)
def clickhouse_mutation_count():
    from statshog.defaults.django import statsd

    from posthog.client import sync_execute

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

    with pushed_metrics_registry("celery_clickhouse_mutation_count") as registry:
        mutations_count_gauge = Gauge(
            "posthog_celery_clickhouse_table_mutations_count",
            "Number of mutations per ClickHouse table.",
            labelnames=["table"],
            registry=registry,
        )
    for table, muts in rows:
        mutations_count_gauge.labels(table=table).set(muts)
        statsd.gauge(
            f"posthog_celery_clickhouse_table_mutations_count",
            muts,
            tags={"table": table},
        )


@app.task(ignore_result=True)
def clickhouse_clear_removed_data():
    from posthog.models.async_deletion.delete_cohorts import AsyncCohortDeletion
    from posthog.models.async_deletion.delete_events import AsyncEventDeletion

    runner = AsyncEventDeletion()
    runner.mark_deletions_done()
    runner.run()

    cohort_runner = AsyncCohortDeletion()
    cohort_runner.mark_deletions_done()
    cohort_runner.run()


@app.task(ignore_result=True)
def clear_clickhouse_deleted_person():
    from posthog.models.async_deletion.delete_person import remove_deleted_person_data

    remove_deleted_person_data()


@app.task(ignore_result=True)
def redis_celery_queue_depth():
    try:
        with pushed_metrics_registry("redis_celery_queue_depth_registry") as registry:
            celery_task_queue_depth_gauge = Gauge(
                "posthog_celery_queue_depth",
                "We use this to monitor the depth of the celery queue.",
                registry=registry,
            )

            llen = get_client().llen("celery")
            celery_task_queue_depth_gauge.set(llen)
    except:
        # if we can't generate the metric don't complain about it.
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
def monitoring_check_clickhouse_schema_drift():
    from posthog.tasks.check_clickhouse_schema_drift import (
        check_clickhouse_schema_drift,
    )

    check_clickhouse_schema_drift()


@app.task(ignore_result=True)
def calculate_cohort():
    from posthog.tasks.calculate_cohort import calculate_cohorts

    calculate_cohorts()


@app.task(ignore_result=True)
def process_scheduled_changes():
    from posthog.tasks.process_scheduled_changes import process_scheduled_changes

    process_scheduled_changes()


@app.task(ignore_result=True)
def sync_insight_cache_states_task():
    from posthog.caching.insight_caching_state import sync_insight_cache_states

    sync_insight_cache_states()


@app.task(ignore_result=True)
def schedule_cache_updates_task():
    from posthog.caching.insight_cache import schedule_cache_updates

    schedule_cache_updates()


@app.task(ignore_result=True)
def update_cache_task(caching_state_id: UUID):
    from posthog.caching.insight_cache import update_cache

    update_cache(caching_state_id)


@app.task(ignore_result=True)
def sync_insight_caching_state(
    team_id: int,
    insight_id: Optional[int] = None,
    dashboard_tile_id: Optional[int] = None,
):
    from posthog.caching.insight_caching_state import sync_insight_caching_state

    sync_insight_caching_state(team_id, insight_id, dashboard_tile_id)


@app.task(ignore_result=True, bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")


@app.task(ignore_result=True)
def calculate_decide_usage() -> None:
    from django.db.models import Q

    from posthog.models import Team
    from posthog.models.feature_flag.flag_analytics import capture_team_decide_usage

    ph_client = get_ph_client()

    for team in Team.objects.select_related("organization").exclude(
        Q(organization__for_internal_metrics=True) | Q(is_demo=True)
    ):
        capture_team_decide_usage(ph_client, team.id, team.uuid)

    ph_client.shutdown()


@app.task(ignore_result=True)
def calculate_external_data_rows_synced() -> None:
    from django.db.models import Q

    from posthog.models import Team
    from posthog.tasks.warehouse import (
        capture_workspace_rows_synced_by_team,
        check_external_data_source_billing_limit_by_team,
    )

    for team in Team.objects.select_related("organization").exclude(
        Q(organization__for_internal_metrics=True) | Q(is_demo=True) | Q(external_data_workspace_id__isnull=True)
    ):
        capture_workspace_rows_synced_by_team.delay(team.pk)
        check_external_data_source_billing_limit_by_team.delay(team.pk)


@app.task(ignore_result=True)
def find_flags_with_enriched_analytics():
    from datetime import datetime, timedelta

    from posthog.models.feature_flag.flag_analytics import (
        find_flags_with_enriched_analytics,
    )

    end = datetime.now()
    begin = end - timedelta(hours=12)

    find_flags_with_enriched_analytics(begin, end)


@app.task(ignore_result=True)
def demo_reset_master_team():
    from posthog.tasks.demo_reset_master_team import demo_reset_master_team

    if is_cloud() or settings.DEMO:
        demo_reset_master_team()


@app.task(ignore_result=True)
def sync_all_organization_available_features():
    from posthog.tasks.sync_all_organization_available_features import (
        sync_all_organization_available_features,
    )

    sync_all_organization_available_features()


@app.task(ignore_result=False, track_started=True, max_retries=0)
def check_async_migration_health():
    from posthog.tasks.async_migrations import check_async_migration_health

    check_async_migration_health()


@app.task(ignore_result=True)
def verify_persons_data_in_sync():
    from posthog.tasks.verify_persons_data_in_sync import (
        verify_persons_data_in_sync as verify,
    )

    if not is_cloud():
        return

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
            from ee.clickhouse.materialized_columns.analyze import (
                materialize_properties_task,
            )
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
def send_org_usage_reports():
    from posthog.tasks.usage_report import send_all_org_usage_reports

    send_all_org_usage_reports.delay()


@app.task(ignore_result=True)
def update_quota_limiting():
    try:
        from ee.billing.quota_limiting import update_all_org_billing_quotas

        update_all_org_billing_quotas()
    except ImportError:
        pass


@app.task(ignore_result=True)
def schedule_all_subscriptions():
    try:
        from ee.tasks.subscriptions import (
            schedule_all_subscriptions as _schedule_all_subscriptions,
        )
    except ImportError:
        pass
    else:
        _schedule_all_subscriptions()


@app.task(ignore_result=True, retries=3)
def clickhouse_send_license_usage():
    try:
        if not is_cloud():
            from ee.tasks.send_license_usage import send_license_usage

            send_license_usage()
    except ImportError:
        pass


@app.task(ignore_result=True)
def check_flags_to_rollback():
    try:
        from ee.tasks.auto_rollback_feature_flag import check_flags_to_rollback

        check_flags_to_rollback()
    except ImportError:
        pass


@app.task(ignore_result=True)
def ee_persist_single_recording(id: str, team_id: int):
    try:
        from ee.session_recordings.persistence_tasks import persist_single_recording

        persist_single_recording(id, team_id)
    except ImportError:
        pass


@app.task(ignore_result=True)
def ee_persist_finished_recordings():
    try:
        from ee.session_recordings.persistence_tasks import persist_finished_recordings
    except ImportError:
        pass
    else:
        persist_finished_recordings()


@app.task(ignore_result=True)
def sync_datawarehouse_sources():
    try:
        from posthog.tasks.warehouse import sync_resources
    except ImportError:
        pass
    else:
        sync_resources()
