from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings

import dagster
import dagster_slack
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import Feature
from posthog.clickhouse.warehouse_object_reads import (
    REPLACE_SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL,
    SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
    SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE,
    SORT_KEY_COLUMNS,
    ReadKind,
    SubjectKind,
)
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.common import EXECUTING_RUN_STATUSES, describe_runs
from posthog.dags.common.resources import SatelliteClickhouseClusterResource
from posthog.dags.slack_alerts import notification_channel_per_team, send_slack_alert

from products.web_analytics.dags.web_preaggregated_utils import (
    get_partitions,
    recreate_staging_table,
    swap_partitions_from_staging,
    sync_partitions_on_replicas,
)

TEMPORAL_QUERY_KIND = "temporal"
DEPLOYED_CLOUD_REGIONS = ("US", "EU", "DEV")
QUERY_FINISH_TYPE = "QueryFinish"
MAX_EXECUTION_TIME_SECONDS = 30 * 60
ONE_GIB = 1024**3
MAX_MEMORY_USAGE_BYTES = 8 * ONE_GIB
SPILL_GROUP_BY_AFTER_BYTES = 2 * ONE_GIB
MAX_THREADS = 8
ROLLUP_NODE_ROLE = NodeRole.AUX
ROLLUP_START_DATE = "2026-09-17"
SCHEDULE_HOUR_UTC = 7
OVERDUE_AFTER_UTC = time(hour=10)
OVERDUE_CHECK_INTERVAL_SECONDS = 60 * 60
CONCURRENCY_TAG = {"warehouse_object_reads_backfill_concurrency": "warehouse_object_reads_v1"}
MAX_RUNTIME_SECONDS = 60 * 60
STUCK_RUN_AGE = timedelta(hours=3)

PARTITION_ID_FORMAT = "%Y%m%d"
READ_SUBJECT_ID = "read_subject_id"
DIRECTLY_READ_IDS = "JSONExtract(log_comment, 'directly_read_ids', 'Array(String)')"
MATERIALIZED_SAVED_QUERY_ID = "JSONExtractString(log_comment, 'materialized_saved_query_id')"
SUBJECT_ID_TAGS = {
    SubjectKind.SAVED_QUERY: "saved_query_ids",
    SubjectKind.TABLE: "warehouse_table_ids",
}

AGGREGATE_COLUMNS = (
    "uniqState(request_id) AS requests",
    "uniqState(user_id) AS users",
    "count() AS read_count",
    "sum(query_duration_ms) AS duration_ms_sum",
    "sum(read_bytes) AS read_bytes_sum",
    "quantilesState(0.5, 0.9)(query_duration_ms) AS duration_ms_quantiles",
    "quantilesState(0.5, 0.9)(read_bytes) AS read_bytes_quantiles",
    "max(event_time) AS max_event_time",
)

QUERY_LOG_COLUMNS = (
    "event_date, event_time, is_initial_query, type, query_id, query_duration_ms, read_bytes, log_comment"
)

SOURCE_ROW_FILTER = f"""event_date = %(day)s
        AND event_time >= %(day_start)s AND event_time < %(day_end)s
        AND is_initial_query
        AND type = '{QUERY_FINISH_TYPE}'
        AND NOT JSONExtractBool(log_comment, 'is_impersonated')"""

REFRESH_ROW_FILTER = f"""position(log_comment, '"materialized_saved_query_id"') > 0
        AND JSONExtractString(log_comment, 'feature') = '{Feature.DATA_MODELING.value}'
        AND JSONExtractString(log_comment, 'kind') = '{TEMPORAL_QUERY_KIND}'
        AND {MATERIALIZED_SAVED_QUERY_ID} != ''"""

daily_partitions = dagster.DailyPartitionsDefinition(start_date=ROLLUP_START_DATE, timezone="UTC")


def query_log_clusters() -> tuple[str, ...]:
    # Warehouse reads run on the main, logs and endpoints clusters in the cloud. Local stacks have only the main one.
    if settings.CLOUD_DEPLOYMENT in DEPLOYED_CLOUD_REGIONS:
        return (settings.CLICKHOUSE_CLUSTER, "logs", "endpoints")
    return (settings.CLICKHOUSE_CLUSTER,)


def query_log_source() -> str:
    # It keeps 14 days, so a day older than that rolls up to nothing and the published day is kept.
    branches = " UNION ALL ".join(
        f"SELECT {QUERY_LOG_COLUMNS} FROM clusterAllReplicas('{cluster}', system.query_log)"
        for cluster in query_log_clusters()
    )
    return f"({branches})"


def _source_branch_sql(
    *,
    source: str,
    read_kind: ReadKind,
    subject_kind: SubjectKind,
    subject_id_column: str,
    workflow_id_column: str,
    read_alone_expression: str,
    array_join: str,
    extra_filter: str,
) -> str:
    return f"""
    SELECT
        JSONExtractInt(log_comment, 'team_id') AS team_id,
        toDate(%(day)s) AS day,
        '{read_kind.value}' AS read_kind,
        '{subject_kind.value}' AS subject_kind,
        {subject_id_column} AS subject_id,
        {workflow_id_column} AS workflow_id,
        JSONExtractString(log_comment, 'kind') AS lc_kind,
        JSONExtractString(log_comment, 'product') AS lc_product,
        JSONExtractString(log_comment, 'feature') AS lc_feature,
        JSONExtractString(log_comment, 'access_method') AS lc_access_method,
        JSONExtractString(log_comment, 'source') AS source,
        JSONExtractString(log_comment, 'scene') AS scene,
        JSONExtractInt(log_comment, 'user_id') > 0 AS has_user_id,
        if(JSONExtractString(log_comment, 'client_query_id') = '', query_id, JSONExtractString(log_comment, 'client_query_id')) AS request_id,
        JSONExtractInt(log_comment, 'user_id') AS user_id,
        query_duration_ms,
        read_bytes,
        event_time,
        {read_alone_expression} AS read_alone
    FROM {source}
    {array_join}
    WHERE {SOURCE_ROW_FILTER}{extra_filter}"""


def _subject_reads_sql(source: str, subject_kind: SubjectKind) -> str:
    tag = SUBJECT_ID_TAGS[subject_kind]
    return _source_branch_sql(
        source=source,
        read_kind=ReadKind.READ,
        subject_kind=subject_kind,
        subject_id_column=READ_SUBJECT_ID,
        workflow_id_column="''",
        read_alone_expression=f"{DIRECTLY_READ_IDS} = [{READ_SUBJECT_ID}]",
        array_join=f"ARRAY JOIN JSONExtract(log_comment, '{tag}', 'Array(String)') AS {READ_SUBJECT_ID}",
        # Skips the JSON parse for the many queries that carry no warehouse tag.
        extra_filter=f"\n        AND position(log_comment, '\"{tag}\"') > 0",
    )


def _refresh_reads_sql(source: str) -> str:
    return _source_branch_sql(
        source=source,
        read_kind=ReadKind.REFRESH,
        subject_kind=SubjectKind.SAVED_QUERY,
        subject_id_column=MATERIALIZED_SAVED_QUERY_ID,
        workflow_id_column="JSONExtractString(log_comment, 'temporal', 'workflow_id')",
        read_alone_expression="false",
        array_join="",
        extra_filter=f"\n        AND {REFRESH_ROW_FILTER}",
    )


def rollup_source_sql(source: str) -> str:
    return f"""{_subject_reads_sql(source, SubjectKind.SAVED_QUERY)}
UNION ALL{_subject_reads_sql(source, SubjectKind.TABLE)}
UNION ALL{_refresh_reads_sql(source)}
"""


def insert_rollup_sql(source: str) -> str:
    return f"""
INSERT INTO {SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE}
SELECT
    {", ".join(SORT_KEY_COLUMNS)},
    {", ".join(AGGREGATE_COLUMNS)}
FROM ({rollup_source_sql(source)})
GROUP BY {", ".join(SORT_KEY_COLUMNS)}
"""


def count_rollup_source_rows_sql(source: str) -> str:
    return f"SELECT count() FROM ({rollup_source_sql(source)})"


TRUNCATE_STAGING_SQL = f"TRUNCATE TABLE {SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE}"


def _day_query_parameters(day: date) -> dict[str, date | datetime | str]:
    day_start = datetime.combine(day, time.min)
    return {
        "day": day,
        "day_start": day_start,
        "day_end": day_start + timedelta(days=1),
    }


def _rollup_query_settings(context: dagster.OpExecutionContext) -> dict[str, str | int]:
    return {
        **settings_with_log_comment(context),
        "max_bytes_before_external_group_by": SPILL_GROUP_BY_AFTER_BYTES,
        "max_threads": MAX_THREADS,
    }


def insert_rollup_into_staging(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    day: date,
) -> None:
    def stage_day(client: Client) -> None:
        client.execute(TRUNCATE_STAGING_SQL)
        client.execute(
            insert_rollup_sql(query_log_source()), _day_query_parameters(day), settings=_rollup_query_settings(context)
        )

    cluster.any_host_by_roles(stage_day, [ROLLUP_NODE_ROLE]).result()


def count_rollup_source_rows(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> int:
    [[source_rows]] = cluster.any_host_by_roles(
        lambda client: client.execute(
            count_rollup_source_rows_sql(query_log_source()),
            _day_query_parameters(day),
            settings=_rollup_query_settings(context),
        ),
        [ROLLUP_NODE_ROLE],
    ).result()
    return source_rows


def refuse_to_run_beside_another_rollup(context: dagster.OpExecutionContext) -> None:
    others = describe_runs(
        context.instance,
        (context.job_name,),
        statuses=EXECUTING_RUN_STATUSES,
        created_after=datetime.now(UTC) - STUCK_RUN_AGE,
        exclude_run_id=context.run_id,
    )
    if others:
        raise dagster.Failure(
            description=f"{'; '.join(others)} is executing, and every run shares one staging table. "
            "Wait for that run to finish, then run this day again."
        )


def publish_day(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> None:
    sync_partitions_on_replicas(
        context, cluster, SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE, node_role=ROLLUP_NODE_ROLE
    )
    staged_partitions = get_partitions(
        context,
        cluster,
        SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        filter_by_partition_window=True,
        node_role=ROLLUP_NODE_ROLE,
    )
    day_partition = day.strftime(PARTITION_ID_FORMAT)
    if staged_partitions == [day_partition]:
        swap_partitions_from_staging(
            context,
            cluster,
            SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE,
            SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
            node_role=ROLLUP_NODE_ROLE,
        )
        return
    if staged_partitions:
        raise dagster.Failure(
            description=f"Staging holds partitions {staged_partitions}, not only {day_partition}. "
            "Nothing was published."
        )
    source_rows = count_rollup_source_rows(context, cluster, day)
    if source_rows:
        raise dagster.Failure(
            description=f"The query log has {source_rows} reads for {day}, but staging is empty. "
            "The published day was kept. Run the day again."
        )
    raise dagster.Failure(
        description=f"The query log has no reads for {day}. Query tagging may be broken. The published day was kept."
    )


@dagster.op
def rollup_warehouse_object_reads_for_day(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    refuse_to_run_beside_another_rollup(context)
    day = date.fromisoformat(context.partition_key)
    context.log.info(f"Rolling up warehouse object reads for {day}")

    recreate_staging_table(
        context,
        cluster,
        SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        REPLACE_SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE_SQL,
        node_role=ROLLUP_NODE_ROLE,
    )
    insert_rollup_into_staging(context, cluster, day)
    publish_day(context, cluster, day)


@dagster.job(
    partitions_def=daily_partitions,
    resource_defs={
        "cluster": SatelliteClickhouseClusterResource(
            satellite_cluster=settings.CLICKHOUSE_AUX_CLUSTER,
            max_execution_time=MAX_EXECUTION_TIME_SECONDS,
            max_memory_usage=MAX_MEMORY_USAGE_BYTES,
        )
    },
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value, "dagster/max_runtime": MAX_RUNTIME_SECONDS, **CONCURRENCY_TAG},
)
def warehouse_object_reads_daily_job() -> None:
    rollup_warehouse_object_reads_for_day()


warehouse_object_reads_daily_schedule = dagster.build_schedule_from_partitioned_job(
    warehouse_object_reads_daily_job,
    hour_of_day=SCHEDULE_HOUR_UTC,
    minute_of_hour=0,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)


def has_published_day(instance: dagster.DagsterInstance, day: date) -> bool:
    return bool(
        instance.get_run_records(
            dagster.RunsFilter(
                job_name=warehouse_object_reads_daily_job.name,
                statuses=[dagster.DagsterRunStatus.SUCCESS],
                tags={"dagster/partition": day.isoformat()},
            ),
            limit=1,
        )
    )


@dagster.sensor(
    minimum_interval_seconds=OVERDUE_CHECK_INTERVAL_SECONDS,
    default_status=dagster.DefaultSensorStatus.RUNNING,
)
def warehouse_object_reads_daily_overdue_sensor(
    context: dagster.SensorEvaluationContext, slack: dagster_slack.SlackResource
) -> dagster.SkipReason | None:
    now = datetime.now(UTC)
    if now.time() < OVERDUE_AFTER_UTC:
        return dagster.SkipReason(f"The rollup is not overdue before {OVERDUE_AFTER_UTC} UTC.")
    day = now.date() - timedelta(days=1)
    if context.cursor == day.isoformat():
        return dagster.SkipReason(f"Already alerted that {day} is missing.")
    if has_published_day(context.instance, day):
        return dagster.SkipReason(f"{day} is published.")
    if not settings.CLOUD_DEPLOYMENT:
        return dagster.SkipReason(f"{day} is missing, but alerts only go out in cloud deployments.")

    job_url = f"https://{settings.DAGSTER_DOMAIN}/locations/clickhouse/jobs/{warehouse_object_reads_daily_job.name}"
    message = (
        f":hourglass: `{warehouse_object_reads_daily_job.name}` has no successful run for {day} "
        f"by {OVERDUE_AFTER_UTC:%H:%M} UTC. Check that its schedule is running and that no run is stuck in the queue: "
        f"<{job_url}|View in Dagster>\nEnvironment: {settings.CLOUD_DEPLOYMENT}"
    )
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": message}}]
    channel = notification_channel_per_team[JobOwners.TEAM_DATA_MODELING.value]
    if send_slack_alert(context, slack.get_client(), channel, blocks, message):
        context.update_cursor(day.isoformat())
    return None
