import time
from typing import Optional
from uuid import UUID

from django.conf import settings
from django.db import connection
from django.utils import timezone

import requests
import posthoganalytics
from celery import shared_task
from prometheus_client import Counter, Gauge
from redis import Redis
from structlog import get_logger

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, limit_concurrency
from posthog.clickhouse.query_tagging import get_query_tags, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.metrics import pushed_metrics_registry
from posthog.ph_client import get_regional_ph_client
from posthog.redis import get_client
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.tasks.utils import CeleryQueue

logger = get_logger(__name__)

# Feature flag last_called_at sync metrics
FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOCK_CONTENTION_COUNTER = Counter(
    "posthog_feature_flag_last_called_at_sync_lock_contentions_total",
    "Times feature flag last_called_at sync was skipped due to lock being held",
)

FEATURE_FLAG_LAST_CALLED_AT_SYNC_LIMIT_HIT_COUNTER = Counter(
    "posthog_feature_flag_last_called_at_sync_limit_reached_total",
    "Times the ClickHouse query result limit was reached during feature flag last_called_at sync",
)


@shared_task(ignore_result=True)
def delete_expired_exported_assets() -> None:
    from posthog.models import ExportedAsset

    ExportedAsset.delete_expired_assets()


@shared_task(ignore_result=True)
def redis_heartbeat() -> None:
    get_client().set("POSTHOG_HEARTBEAT", int(time.time()))


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ANALYTICS_QUERIES.value,
    acks_late=True,
    autoretry_for=(
        # Important: Only retry for things that might be okay on the next try
        CHQueryErrorTooManySimultaneousQueries,
        ConcurrencyLimitExceeded,
    ),
    retry_backoff=1,
    retry_backoff_max=10,
    max_retries=10,
    expires=60 * 10,  # Do not run queries that got stuck for more than this
    reject_on_worker_lost=True,
    track_started=True,
)
@limit_concurrency(150, limit_name="global")  # Do not go above what CH can handle (max_concurrent_queries)
@limit_concurrency(
    50,
    key=lambda *args, **kwargs: kwargs.get("team_id") or args[0],
    limit_name="per_team",
)  # Do not run too many queries at once for the same team
def process_query_task(
    team_id: int,
    user_id: Optional[int],
    query_id: str,
    query_json: dict,
    query_tags: dict,
    is_query_service: bool,
    limit_context: Optional[LimitContext] = None,
) -> None:
    """
    Kick off query
    Once complete save results to redis
    """
    from posthog.clickhouse.client import execute_process_query

    existing_query_tags = get_query_tags()
    all_query_tags = {**query_tags, **existing_query_tags.model_dump(exclude_unset=True)}
    tag_queries(**all_query_tags)

    if is_query_service:
        tag_queries(chargeable=1)

    execute_process_query(
        team_id=team_id,
        user_id=user_id,
        query_id=query_id,
        query_json=query_json,
        limit_context=limit_context,
        is_query_service=is_query_service,
    )


@shared_task(ignore_result=True)
def pg_table_cache_hit_rate() -> None:
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


@shared_task(ignore_result=True)
def pg_plugin_server_query_timing() -> None:
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


@shared_task(ignore_result=True)
def pg_row_count() -> None:
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

HEARTBEAT_EVENT_TO_INGESTION_LAG_METRIC = {"$heartbeat": "ingestion_api"}


@shared_task(ignore_result=True)
def ingestion_lag() -> None:
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client import sync_execute
    from posthog.models.team.team import Team

    query = """
    SELECT event, date_diff('second', max(timestamp), now())
    FROM events
    WHERE team_id IN %(team_ids)s
        AND event IN %(events)s
        AND timestamp > yesterday() AND timestamp < now() + toIntervalMinute(3)
    GROUP BY event
    """

    team_ids = settings.INGESTION_LAG_METRIC_TEAM_IDS

    try:
        results = sync_execute(
            query,
            {
                "team_ids": team_ids,
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

    for team in Team.objects.filter(pk__in=team_ids):
        requests.post(
            settings.SITE_URL + "/e",
            json={
                "event": "$heartbeat",
                "distinct_id": "posthog-celery-heartbeat",
                "token": team.api_token,
                "properties": {"$timestamp": timezone.now().isoformat()},
            },
        )


@shared_task(ignore_result=True, queue=CeleryQueue.SESSION_REPLAY_GENERAL.value)
def replay_count_metrics() -> None:
    try:
        logger.info("[replay_count_metrics] running task")

        from posthog.clickhouse.client import sync_execute

        # ultimately I want to observe values by team id, but at the moment that would be lots of series, let's reduce the value first
        query = """
        select
            --team_id,
            count() as all_recordings,
            countIf(snapshot_source == 'mobile') as mobile_recordings,
            countIf(snapshot_source == 'web') as web_recordings,
            countIf(snapshot_source =='web' and first_url is null) as invalid_web_recordings
        from (
            select any(team_id) as team_id, argMinMerge(first_url) as first_url, argMinMerge(snapshot_source) as snapshot_source
            from session_replay_events
            where min_first_timestamp >= now() - interval 65 minute
            and min_first_timestamp <= now() - interval 5 minute
            group by session_id
        )
        --group by team_id
        """

        results = sync_execute(
            query,
        )

        metrics = [
            "all_recordings",
            "mobile_recordings",
            "web_recordings",
            "invalid_web_recordings",
        ]
        descriptions = [
            "All recordings that started in the last hour",
            "Recordings started in the last hour that are from mobile",
            "Recordings started in the last hour that are from web",
            "Acts as a proxy for replay sessions which haven't received a full snapshot",
        ]
        with pushed_metrics_registry("celery_replay_tracking") as registry:
            for i in range(0, 4):
                gauge = Gauge(
                    f"replay_tracking_{metrics[i]}",
                    descriptions[i],
                    registry=registry,
                )
                count = results[0][i]
                gauge.set(count)
    except Exception as e:
        logger.exception("Failed to run invalid web replays task", error=e, inc_exc_info=True)


KNOWN_CELERY_TASK_IDENTIFIERS = {
    "pluginJob",
    "runEveryHour",
    "runEveryMinute",
    "runEveryDay",
}


@shared_task(ignore_result=True)
def clickhouse_row_count() -> None:
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client import sync_execute

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


@shared_task(ignore_result=True)
def clickhouse_errors_count() -> None:
    """
    This task is used to track the recency of errors in ClickHouse.
    We can use this to alert on errors that are consistently being generated recently
    999 - KEEPER_EXCEPTION
    225 - NO_ZOOKEEPER
    242 - TABLE_IS_READ_ONLY
    """
    from posthog.clickhouse.client import sync_execute

    QUERY = """
        select
            getMacro('replica') replica,
            getMacro('shard') shard,
            name,
            value as errors,
            dateDiff('minute', last_error_time, now()) minutes_ago
        from clusterAllReplicas(%(cluster)s, system.errors)
        where code in (999, 225, 242)
        order by minutes_ago
    """
    params = {
        "cluster": CLICKHOUSE_CLUSTER,
    }
    rows = sync_execute(QUERY, params)
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


@shared_task(ignore_result=True)
def clickhouse_part_count() -> None:
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client import sync_execute

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


@shared_task(ignore_result=True)
def clickhouse_mutation_count() -> None:
    from statshog.defaults.django import statsd

    from posthog.clickhouse.client import sync_execute

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


@shared_task(ignore_result=True)
def clickhouse_clear_removed_data() -> None:
    from posthog.models.async_deletion.delete_cohorts import AsyncCohortDeletion
    from posthog.pagerduty.pd import create_incident

    cohort_runner = AsyncCohortDeletion()

    try:
        cohort_runner.mark_deletions_done()
    except Exception as e:
        logger.error("Failed to mark cohort deletions done", error=e, exc_info=True)
        create_incident("Failed to mark cohort deletions done", "clickhouse_clear_removed_data", severity="error")

    try:
        cohort_runner.run()
    except Exception as e:
        logger.error("Failed to run cohort deletions", error=e, exc_info=True)
        create_incident("Failed to run cohort deletions", "clickhouse_clear_removed_data", severity="error")


@shared_task(ignore_result=True)
def clear_clickhouse_deleted_person() -> None:
    from posthog.models.async_deletion.delete_person import remove_deleted_person_data

    remove_deleted_person_data()


@shared_task(ignore_result=True, queue=CeleryQueue.STATS.value)
def redis_celery_queue_depth() -> None:
    try:
        with pushed_metrics_registry("redis_celery_queue_depth_registry") as registry:
            celery_task_queue_depth_gauge = Gauge(
                "posthog_celery_queue_depth",
                "We use this to monitor the depth of the celery queue.",
                registry=registry,
                labelnames=["queue_name"],
            )

            for queue in CeleryQueue:
                llen = get_client().llen(queue.value)
                celery_task_queue_depth_gauge.labels(queue_name=queue.value).set(llen)

    except:
        # if we can't generate the metric don't complain about it.
        return


@shared_task(ignore_result=True)
def update_event_partitions() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "DO $$ BEGIN IF (SELECT exists(select * from pg_proc where proname = 'update_partitions')) THEN PERFORM update_partitions(); END IF; END $$"
        )


@shared_task(ignore_result=True)
def clean_stale_partials() -> None:
    """Clean stale (meaning older than 7 days) partial social auth sessions."""
    from social_django.models import Partial

    Partial.objects.filter(timestamp__lt=timezone.now() - timezone.timedelta(7)).delete()


@shared_task(ignore_result=True)
def calculate_cohort(parallel_count: int) -> None:
    from posthog.tasks.calculate_cohort import enqueue_cohorts_to_calculate, reset_stuck_cohorts

    enqueue_cohorts_to_calculate(parallel_count)
    reset_stuck_cohorts()


class Polling:
    _SINGLETON_REDIS_KEY = "POLL_QUERY_PERFORMANCE_SINGLETON_REDIS_KEY"
    NANOSECONDS_IN_SECOND = int(1e9)
    TIME_BETWEEN_RUNS_SECONDS = 2
    SOFT_TIME_LIMIT_SECONDS = 10
    HARD_TIME_LIMIT_SECONDS = 12
    ASSUME_TASK_DEAD_SECONDS = 14  # the time after which we start a new task

    TIME_BETWEEN_RUNS_NANOSECONDS = NANOSECONDS_IN_SECOND * TIME_BETWEEN_RUNS_SECONDS
    ASSUME_TASK_DEAD_NANOSECONDS = NANOSECONDS_IN_SECOND * ASSUME_TASK_DEAD_SECONDS

    @staticmethod
    def _encode_redis_key(time_ns: int) -> bytes:
        return time_ns.to_bytes(8, "big")

    @staticmethod
    def _decode_redis_key(time_ns: bytes | None) -> int:
        return 0 if time_ns is None else int.from_bytes(time_ns, "big")

    @staticmethod
    def set_last_run_time(client: Redis, time_ns: int) -> None:
        client.set(Polling._SINGLETON_REDIS_KEY, Polling._encode_redis_key(time_ns))

    @staticmethod
    def get_last_run_time(client: Redis) -> int:
        return Polling._decode_redis_key(client.get(Polling._SINGLETON_REDIS_KEY))


@shared_task(
    ignore_result=True,
    max_retries=0,
    soft_time_limit=Polling.SOFT_TIME_LIMIT_SECONDS,
    time_limit=Polling.HARD_TIME_LIMIT_SECONDS,
)
def poll_query_performance(last_known_run_time_ns: int) -> None:
    start_time_ns = time.time_ns()

    try:
        redis_client = get_client()
        if Polling.get_last_run_time(redis_client) != last_known_run_time_ns:
            logger.error("Poll query performance task terminating: another poller is running")
            return
        Polling.set_last_run_time(redis_client, start_time_ns)
        from posthog.tasks.poll_query_performance import poll_query_performance as poll_query_performance_nontask

        poll_query_performance_nontask()
    except Exception as e:
        logger.exception("Poll query performance failed", error=e)

    elapsed_ns = time.time_ns() - start_time_ns
    if elapsed_ns > Polling.TIME_BETWEEN_RUNS_NANOSECONDS:
        # right again right away if more than time_between_runs has elapsed
        poll_query_performance.delay(start_time_ns)
    else:
        # delay until time_between_runs has elapsed
        poll_query_performance.apply_async(
            args=[start_time_ns],
            countdown=((Polling.TIME_BETWEEN_RUNS_NANOSECONDS - elapsed_ns) / Polling.NANOSECONDS_IN_SECOND),
        )


@shared_task(ignore_result=True, max_retries=1)
def start_poll_query_performance() -> None:
    redis_client = get_client()
    last_run_start_time_ns = Polling.get_last_run_time(redis_client)
    now_ns: int = time.time_ns()
    try:
        # The key should never be in the future
        # If the key is in the future or more than 15 seconds in the past, start a worker
        if last_run_start_time_ns > now_ns + Polling.TIME_BETWEEN_RUNS_NANOSECONDS:
            logger.error("Restarting poll query performance because key is in future")
            poll_query_performance.delay(last_run_start_time_ns)
        elif now_ns - last_run_start_time_ns > Polling.ASSUME_TASK_DEAD_NANOSECONDS:
            logger.error("Restarting poll query performance because of a long delay")
            poll_query_performance.delay(last_run_start_time_ns)

    except Exception as e:
        logger.exception("Restarting poll query performance because of an error", error=e)
        poll_query_performance.delay(last_run_start_time_ns)


@shared_task(ignore_result=True)
def process_scheduled_changes() -> None:
    from posthog.tasks.process_scheduled_changes import process_scheduled_changes

    process_scheduled_changes()


@shared_task(ignore_result=True)
def sync_insight_cache_states_task() -> None:
    from posthog.caching.insight_caching_state import sync_insight_cache_states

    sync_insight_cache_states()


@shared_task(ignore_result=True)
def schedule_cache_updates_task() -> None:
    from posthog.caching.insight_cache import schedule_cache_updates

    schedule_cache_updates()


@shared_task(
    ignore_result=True,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=10,
    retry_backoff_max=30,
    max_retries=3,
    retry_jitter=True,
    queue=CeleryQueue.LONG_RUNNING.value,
)
def update_cache_task(caching_state_id: UUID) -> None:
    from posthog.caching.insight_cache import update_cache

    update_cache(caching_state_id)


@shared_task(ignore_result=True)
def sync_insight_caching_state(
    team_id: int,
    insight_id: Optional[int] = None,
    dashboard_tile_id: Optional[int] = None,
) -> None:
    from posthog.caching.insight_caching_state import sync_insight_caching_state

    sync_insight_caching_state(team_id, insight_id, dashboard_tile_id)


@shared_task(ignore_result=True)
def calculate_decide_usage() -> None:
    from posthog.models.feature_flag.flag_analytics import (
        capture_usage_for_all_teams as capture_decide_usage_for_all_teams,
    )

    ph_client = get_regional_ph_client()

    if ph_client:
        capture_decide_usage_for_all_teams(ph_client)
        ph_client.shutdown()


@shared_task(ignore_result=True)
def find_flags_with_enriched_analytics() -> None:
    from datetime import datetime, timedelta

    from posthog.models.feature_flag.flag_analytics import find_flags_with_enriched_analytics

    end = datetime.now()
    begin = end - timedelta(hours=12)

    find_flags_with_enriched_analytics(begin, end)


@shared_task(ignore_result=True)
def demo_reset_master_team() -> None:
    from posthog.tasks.demo_reset_master_team import demo_reset_master_team

    if is_cloud() or settings.DEMO:
        demo_reset_master_team()


@shared_task(ignore_result=True)
def sync_all_organization_available_product_features() -> None:
    from posthog.tasks.sync_all_organization_available_product_features import (
        sync_all_organization_available_product_features,
    )

    sync_all_organization_available_product_features()


@shared_task(ignore_result=False, track_started=True, max_retries=0)
def check_async_migration_health() -> None:
    from posthog.tasks.async_migrations import check_async_migration_health

    check_async_migration_health()


@shared_task(ignore_result=True)
def verify_persons_data_in_sync() -> None:
    from posthog.tasks.verify_persons_data_in_sync import verify_persons_data_in_sync as verify

    if not is_cloud():
        return

    verify()


@shared_task(ignore_result=True)
def stop_surveys_reached_target() -> None:
    from posthog.tasks.stop_surveys_reached_target import stop_surveys_reached_target

    stop_surveys_reached_target()


@shared_task(ignore_result=True)
def update_survey_iteration() -> None:
    from posthog.tasks.update_survey_iteration import update_survey_iteration

    update_survey_iteration()


@shared_task(ignore_result=True)
def update_survey_adaptive_sampling() -> None:
    from posthog.tasks.update_survey_adaptive_sampling import update_survey_adaptive_sampling

    update_survey_adaptive_sampling()


def recompute_materialized_columns_enabled() -> bool:
    from posthog.models.instance_setting import get_instance_setting

    if get_instance_setting("MATERIALIZED_COLUMNS_ENABLED") and get_instance_setting(
        "COMPUTE_MATERIALIZED_COLUMNS_ENABLED"
    ):
        return True
    return False


@shared_task(ignore_result=True)
def clickhouse_materialize_columns() -> None:
    if recompute_materialized_columns_enabled():
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize_properties_task
        except ImportError:
            pass
        else:
            materialize_properties_task()


@shared_task(ignore_result=True, queue=CeleryQueue.USAGE_REPORTS.value)
def send_org_usage_reports() -> None:
    from posthog.tasks.usage_report import send_all_org_usage_reports

    send_all_org_usage_reports.delay()


@shared_task(ignore_result=True)
def schedule_all_subscriptions() -> None:
    try:
        from ee.tasks.subscriptions import schedule_all_subscriptions as _schedule_all_subscriptions
    except ImportError:
        pass
    else:
        _schedule_all_subscriptions()


@shared_task(ignore_result=True, retries=3)
def clickhouse_send_license_usage() -> None:
    try:
        if not is_cloud():
            from ee.tasks.send_license_usage import send_license_usage

            send_license_usage()
    except ImportError:
        pass


@shared_task(ignore_result=True)
def check_flags_to_rollback() -> None:
    try:
        from ee.tasks.auto_rollback_feature_flag import check_flags_to_rollback

        check_flags_to_rollback()
    except ImportError:
        pass


@shared_task(ignore_result=True)
def ee_persist_single_recording_v2(id: str, team_id: int) -> None:
    try:
        from ee.session_recordings.persistence_tasks import persist_single_recording_v2

        persist_single_recording_v2(id, team_id)
    except ImportError:
        pass


@shared_task(ignore_result=True)
def ee_persist_finished_recordings_v2() -> None:
    try:
        from ee.session_recordings.persistence_tasks import persist_finished_recordings_v2
    except ImportError:
        pass
    else:
        persist_finished_recordings_v2()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.SESSION_REPLAY_GENERAL.value,
)
def count_items_in_playlists() -> None:
    try:
        from ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
            enqueue_recordings_that_match_playlist_filters,
        )
    except ImportError as ie:
        posthoganalytics.capture_exception(ie, properties={"posthog_feature": "session_replay_playlist_counters"})
        logger.exception("Failed to import task to count items in playlists", error=ie)
    else:
        enqueue_recordings_that_match_playlist_filters()


@shared_task(ignore_result=True)
def environments_rollback_migration(organization_id: int, environment_mappings: dict[str, int], user_id: int) -> None:
    from posthog.tasks.environments_rollback import environments_rollback_migration

    environments_rollback_migration(organization_id, environment_mappings, user_id)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def background_delete_model_task(
    model_name: str, team_id: int, batch_size: int = 10000, records_to_delete: int | None = None
) -> None:
    """
    Background task to delete records from a model in batches.

    Args:
        model_name: Django model name in format 'app_label.model_name'
        team_id: Team ID to filter records for deletion
        batch_size: Number of records to delete per batch
        records_to_delete: Maximum number of records to delete (None means delete all)
    """
    import logging

    from django.apps import apps

    import structlog

    logger = structlog.get_logger(__name__)
    logger.setLevel(logging.INFO)

    try:
        # Parse model name
        app_label, model_label = model_name.split(".")
        model = apps.get_model(app_label, model_label)

        # Determine team field name
        team_field = "team_id" if hasattr(model, "team_id") else "team"

        # Get total count for logging - use raw SQL for better performance
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {model._meta.db_table} WHERE {team_field} = %s", [team_id])
            total_count = cursor.fetchone()[0]
        logger.info(f"Starting background deletion for {model_name}, team_id={team_id}, total={total_count}")

        # Determine how many records to actually delete
        if records_to_delete is not None:
            records_to_delete = min(records_to_delete, total_count)
            logger.info(f"Will delete up to {records_to_delete} records due to records_to_delete limit")
        else:
            records_to_delete = total_count

        # At this point, records_to_delete is guaranteed to be an int
        records_to_delete_int: int = records_to_delete

        deleted_count = 0
        batch_num = 0

        while deleted_count < records_to_delete_int:
            # Calculate how many more records we can delete
            remaining_to_delete = records_to_delete_int - deleted_count
            current_batch_size = min(batch_size, remaining_to_delete)

            # Use raw SQL for both SELECT and DELETE to avoid Django ORM overhead
            with connection.cursor() as cursor:
                # Get batch of IDs to delete - no offset needed since we're deleting as we go
                cursor.execute(
                    f"""
                    SELECT id FROM {model._meta.db_table}
                    WHERE {team_field} = %s
                    LIMIT %s
                    """,
                    [team_id, current_batch_size],
                )
                batch_ids = [row[0] for row in cursor.fetchall()]

            if not batch_ids:
                logger.info(f"No more records to delete for {model_name}, team_id={team_id}")
                break

            # Delete the batch using raw SQL for better performance
            with connection.cursor() as cursor:
                # Use IN clause with parameterized query
                placeholders = ",".join(["%s"] * len(batch_ids))
                cursor.execute(f"DELETE FROM {model._meta.db_table} WHERE id IN ({placeholders})", batch_ids)
                deleted_in_batch = cursor.rowcount

            deleted_count += deleted_in_batch
            batch_num += 1

            logger.info(
                f"Deleted batch {batch_num} for {model_name}, "
                f"team_id={team_id}, batch_size={deleted_in_batch}, "
                f"total_deleted={deleted_count}/{records_to_delete_int}"
            )

            # If we got fewer records than requested, we're done
            if len(batch_ids) < current_batch_size:
                break

            time.sleep(0.2)  # Sleep to avoid overwhelming the database

        logger.info(
            f"Completed background deletion for {model_name}, " f"team_id={team_id}, total_deleted={deleted_count}"
        )

    except Exception as e:
        logger.error(f"Error in background deletion for {model_name}, team_id={team_id}: {str(e)}", exc_info=True)
        raise


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=120,
    max_retries=3,
)
def sync_feature_flag_last_called() -> None:
    """
    Sync last_called_at timestamps from ClickHouse $feature_flag_called events to PostgreSQL.

    This task:
    1. Uses Redis locking to prevent concurrent executions
    2. Gets the last sync timestamp from Redis checkpoint
    3. Queries ClickHouse for flag usage since last sync
    4. Bulk updates PostgreSQL with latest timestamps
    5. Updates the sync checkpoint in Redis

    Concurrency Control:
    - Uses Redis cache lock to prevent overlapping runs
    - Lock timeout matches schedule interval (1800s = 30 minutes)
    - Task expires after 1800 seconds if queued but not started (via scheduled.py)
    - No time limits - task runs until complete

    Configuration (via settings.feature_flags):
    - FEATURE_FLAG_LAST_CALLED_AT_SYNC_BATCH_SIZE: Bulk update batch size (default: 1000)
    - FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT: Max ClickHouse results (default: 100000)
    - FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS: Fallback lookback period (default: 1)
    """
    from datetime import datetime, timedelta

    from django.core.cache import cache

    from posthog.clickhouse.client import sync_execute
    from posthog.exceptions_capture import capture_exception
    from posthog.models.feature_flag.feature_flag import FeatureFlag

    FEATURE_FLAG_LAST_CALLED_SYNC_KEY = "posthog:feature_flag_last_called_sync:last_timestamp"
    LOCK_KEY = "posthog:feature_flag_last_called_sync:lock"
    LOCK_TIMEOUT = 1800  # 30 minutes = schedule interval (prevents concurrent execution)

    # Attempt to acquire lock
    if not cache.add(LOCK_KEY, "locked", timeout=LOCK_TIMEOUT):
        logger.info("Feature flag sync already running, skipping")
        FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOCK_CONTENTION_COUNTER.inc()
        return

    start_time = timezone.now()

    try:
        redis_client = get_client()

        # Get last sync timestamp from Redis or use lookback
        try:
            last_sync_str = redis_client.get(FEATURE_FLAG_LAST_CALLED_SYNC_KEY)
            if last_sync_str:
                parsed_timestamp = datetime.fromisoformat(last_sync_str.decode())
                # Ensure timezone-aware to avoid comparison issues with timezone.now()
                last_sync_timestamp = (
                    parsed_timestamp if parsed_timestamp.tzinfo else timezone.make_aware(parsed_timestamp)
                )
            else:
                last_sync_timestamp = timezone.now() - timedelta(
                    days=settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS
                )
        except Exception as e:
            logger.warning("Failed to get or parse last sync timestamp", error=str(e))
            last_sync_timestamp = timezone.now() - timedelta(
                days=settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS
            )

        current_sync_timestamp = timezone.now()

        logger.info(
            "Starting feature flag sync",
            last_sync_timestamp=last_sync_timestamp.isoformat(),
            current_sync_timestamp=current_sync_timestamp.isoformat(),
        )

        # Query ClickHouse for flag usage since last sync
        # Limit for insurance against large datasets and memory issues during a surge
        result = sync_execute(
            """
            SELECT
                team_id,
                JSONExtractString(properties, '$feature_flag') as flag_key,
                max(timestamp) as last_called_at,
                count() as call_count
            FROM events
            PREWHERE event = '$feature_flag_called'
            WHERE timestamp > %(last_sync_timestamp)s
              AND timestamp <= %(current_sync_timestamp)s
              AND JSONExtractString(properties, '$feature_flag') != ''
            GROUP BY team_id, flag_key
            ORDER BY last_called_at DESC
            LIMIT %(limit)s
            """,
            {
                "last_sync_timestamp": last_sync_timestamp,
                "current_sync_timestamp": current_sync_timestamp,
                "limit": settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT,
            },
        )

        if not result:
            # Update checkpoint even if no results
            redis_client.set(FEATURE_FLAG_LAST_CALLED_SYNC_KEY, current_sync_timestamp.isoformat())

            # Emit metrics for no-results case
            checkpoint_lag_seconds = 0.0  # No lag when checkpoint is set to current time
            with pushed_metrics_registry("feature_flag_last_called_at_sync_completion") as registry:
                Gauge(
                    "posthog_feature_flag_last_called_at_sync_updated_count",
                    "Number of feature flags updated in last sync",
                    registry=registry,
                ).set(0)
                Gauge(
                    "posthog_feature_flag_last_called_at_sync_events_processed",
                    "Number of events processed in last sync",
                    registry=registry,
                ).set(0)
                Gauge(
                    "posthog_feature_flag_last_called_at_sync_clickhouse_results",
                    "Number of results returned from ClickHouse query",
                    registry=registry,
                ).set(0)
                Gauge(
                    "posthog_feature_flag_last_called_at_sync_checkpoint_lag_seconds",
                    "Seconds between checkpoint timestamp and current time",
                    registry=registry,
                ).set(checkpoint_lag_seconds)

            logger.info(
                "Feature flag sync completed with no events",
                duration_seconds=(timezone.now() - start_time).total_seconds(),
            )
            return

        # Collect flags for bulk update
        flags_to_update = []

        # Get latest timestamp for checkpoint, fallback to current if all None
        checkpoint_timestamp = max((row[2] for row in result if row[2]), default=current_sync_timestamp)
        # Ensure timestamp is timezone-aware (ClickHouse returns naive datetimes)
        checkpoint_timestamp = (
            checkpoint_timestamp if checkpoint_timestamp.tzinfo else timezone.make_aware(checkpoint_timestamp)
        )

        # Build lookup map of (team_id, key) -> timestamp from ClickHouse results
        flag_updates = {(row[0], row[1]): row[2] for row in result}

        # Batch fetch all relevant flags in a single query
        team_ids = list({row[0] for row in result})
        flag_keys = list({row[1] for row in result})

        flags = FeatureFlag.objects.filter(team_id__in=team_ids, key__in=flag_keys)

        for flag in flags:
            new_timestamp = flag_updates.get((flag.team_id, flag.key))
            if new_timestamp:
                # Ensure timestamp from ClickHouse is timezone-aware before comparison
                new_timestamp = new_timestamp if new_timestamp.tzinfo else timezone.make_aware(new_timestamp)
                if flag.last_called_at is None or flag.last_called_at < new_timestamp:
                    flag.last_called_at = new_timestamp
                    flags_to_update.append(flag)

        # Perform bulk update
        updated_count = 0
        if flags_to_update:
            try:
                FeatureFlag.objects.bulk_update(
                    flags_to_update,
                    ["last_called_at"],
                    batch_size=settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_BATCH_SIZE,
                )
                updated_count = len(flags_to_update)
            except Exception as e:
                capture_exception(
                    e,
                    additional_properties={
                        "feature": "feature_flags",
                        "task": "sync_feature_flag_last_called",
                        "flags_count": len(flags_to_update),
                    },
                )
                raise

        # Store checkpoint for next sync using the latest timestamp from results
        redis_client.set(FEATURE_FLAG_LAST_CALLED_SYNC_KEY, checkpoint_timestamp.isoformat())

        duration = (timezone.now() - start_time).total_seconds()
        processed_events = sum(row[3] for row in result)
        clickhouse_results = len(result)

        # Emit metrics for successful completion
        checkpoint_lag_seconds = (timezone.now() - checkpoint_timestamp).total_seconds()
        with pushed_metrics_registry("feature_flag_last_called_at_sync_completion") as registry:
            Gauge(
                "posthog_feature_flag_last_called_at_sync_updated_count",
                "Number of feature flags updated in last sync",
                registry=registry,
            ).set(updated_count)
            Gauge(
                "posthog_feature_flag_last_called_at_sync_events_processed",
                "Number of events processed in last sync",
                registry=registry,
            ).set(processed_events)
            Gauge(
                "posthog_feature_flag_last_called_at_sync_clickhouse_results",
                "Number of results returned from ClickHouse query",
                registry=registry,
            ).set(clickhouse_results)
            Gauge(
                "posthog_feature_flag_last_called_at_sync_checkpoint_lag_seconds",
                "Seconds between checkpoint timestamp and current time",
                registry=registry,
            ).set(checkpoint_lag_seconds)

        # Track if we hit the ClickHouse result limit
        if clickhouse_results >= settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT:
            FEATURE_FLAG_LAST_CALLED_AT_SYNC_LIMIT_HIT_COUNTER.inc()

        logger.info(
            "Feature flag sync completed",
            updated_count=updated_count,
            processed_events=processed_events,
            clickhouse_results=clickhouse_results,
            duration_seconds=duration,
        )

        # Alert if approaching schedule interval (25 min warning threshold)
        if duration > 1500:
            logger.warning(
                "Feature flag sync taking longer than expected",
                duration_seconds=duration,
                updated_count=updated_count,
                processed_events=sum(row[3] for row in result),
                recommendation="Consider reducing FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT or optimizing query",
            )

    except Exception as e:
        duration = (timezone.now() - start_time).total_seconds()
        logger.exception("Feature flag sync failed", error=e, duration_seconds=duration)
        capture_exception(
            e, additional_properties={"feature": "feature_flags", "task": "sync_feature_flag_last_called"}
        )
        raise
    finally:
        # Always release the lock
        cache.delete(LOCK_KEY)


@shared_task(ignore_result=True, time_limit=7200)
def refresh_activity_log_fields_cache(flush: bool = False, hours_back: int = 14) -> None:
    """
    Refresh fields cache for large organizations.

    Args:
        flush: If True, delete existing cache and rebuild from scratch
        hours_back: Number of hours to look back (default: 14 = 12h schedule + 2h buffer)
    """

    from uuid import UUID

    from django.db.models import Count

    from posthog.api.advanced_activity_logs.constants import BATCH_SIZE, SAMPLING_PERCENTAGE, SMALL_ORG_THRESHOLD
    from posthog.api.advanced_activity_logs.field_discovery import AdvancedActivityLogFieldDiscovery
    from posthog.api.advanced_activity_logs.fields_cache import delete_cached_fields
    from posthog.exceptions_capture import capture_exception
    from posthog.models import Organization
    from posthog.models.activity_logging.activity_log import ActivityLog

    def _process_org_with_flush(discovery: AdvancedActivityLogFieldDiscovery, org_id: UUID) -> None:
        """Rebuild cache from scratch with sampling."""
        deleted = delete_cached_fields(str(org_id))
        logger.info(f"Flushed cache for org {org_id}: {deleted}")

        record_count = discovery._get_org_record_count()
        estimated_sampled_records = int(record_count * (SAMPLING_PERCENTAGE / 100))
        total_batches = (estimated_sampled_records + BATCH_SIZE - 1) // BATCH_SIZE

        logger.info(
            f"Rebuilding cache for org {org_id} from scratch: "
            f"{record_count} total records, sampling {estimated_sampled_records} records"
        )

        for batch_num in range(total_batches):
            offset = batch_num * BATCH_SIZE
            records = discovery.get_sampled_records(limit=BATCH_SIZE, offset=offset)
            discovery.process_batch_for_large_org(records)

    def _process_org_incremental(discovery: AdvancedActivityLogFieldDiscovery, org_id: UUID, hours_back: int) -> int:
        """Process recent records with 100% coverage."""
        recent_queryset = discovery.get_activity_logs_queryset(hours_back=hours_back)
        recent_count = recent_queryset.count()

        logger.info(f"Processing {recent_count} records from last {hours_back}h for org {org_id} (100% coverage)")

        for batch_num in range(0, recent_count, BATCH_SIZE):
            records = [
                {"scope": record["scope"], "detail": record["detail"]}
                for record in recent_queryset.values("scope", "detail")[batch_num : batch_num + BATCH_SIZE]
            ]
            if records:
                discovery.process_batch_for_large_org(records, hours_back=hours_back)

        return recent_count

    mode = "FLUSH" if flush else f"INCREMENTAL (last {hours_back}h, 100% coverage)"
    logger.info(f"[refresh_activity_log_fields_cache] running task in {mode} mode")

    large_org_data = (
        ActivityLog.objects.values("organization_id")
        .annotate(activity_count=Count("id"))
        .filter(activity_count__gt=SMALL_ORG_THRESHOLD)
        .order_by("-activity_count")
    )

    large_org_ids = [data["organization_id"] for data in large_org_data if data["organization_id"]]
    large_orgs = list(Organization.objects.filter(id__in=large_org_ids))

    org_count = len(large_orgs)
    logger.info(f"[refresh_activity_log_fields_cache] processing {org_count} large organizations")

    processed_orgs = 0
    total_recent_records = 0

    for org in large_orgs:
        try:
            discovery = AdvancedActivityLogFieldDiscovery(org.id)

            if flush:
                _process_org_with_flush(discovery, org.id)
            else:
                recent_count = _process_org_incremental(discovery, org.id, hours_back)
                total_recent_records += recent_count

            processed_orgs += 1

        except Exception as e:
            logger.exception(
                "Failed to refresh activity log fields cache for org",
                org_id=org.id,
                mode=mode,
                error=e,
            )
            capture_exception(e)

    if not flush:
        logger.info(
            f"[refresh_activity_log_fields_cache] completed for {processed_orgs}/{org_count} organizations "
            f"in {mode} mode. Total recent records processed: {total_recent_records}"
        )
    else:
        logger.info(
            f"[refresh_activity_log_fields_cache] completed flush and rebuild for "
            f"{processed_orgs}/{org_count} organizations"
        )
