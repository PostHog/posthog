from datetime import date, time

from django.conf import settings

import dagster
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
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import SatelliteClickhouseClusterResource
from posthog.dags.common.staged_daily_rollup import (
    ONE_GIB,
    build_catch_up_schedule,
    build_overdue_sensor,
    day_query_parameters,
    publish_staged_day,
    query_log_source as staged_rollup_query_log_source,
    refuse_to_run_beside_another_rollup,
    rollup_query_settings,
)

from products.web_analytics.dags.web_preaggregated_utils import recreate_staging_table

TEMPORAL_QUERY_KIND = "temporal"
QUERY_FINISH_TYPE = "QueryFinish"
MAX_EXECUTION_TIME_SECONDS = 30 * 60
MAX_MEMORY_USAGE_BYTES = 8 * ONE_GIB
ROLLUP_NODE_ROLE = NodeRole.AUX
ROLLUP_START_DATE = "2026-09-17"
ATTEMPT_HOURS_UTC = (5, 6, 7)
CATCH_UP_DAYS = 7
OVERDUE_AFTER_UTC = time(hour=10)
OVERDUE_CHECK_INTERVAL_SECONDS = 60 * 60
CONCURRENCY_TAG = {"warehouse_object_reads_backfill_concurrency": "warehouse_object_reads_v1"}
MAX_RUNTIME_SECONDS = 60 * 60

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


def query_log_source() -> str:
    # It keeps 14 days, so a day older than that rolls up to nothing and the published day is kept.
    return staged_rollup_query_log_source(QUERY_LOG_COLUMNS)


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


def insert_rollup_into_staging(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    day: date,
) -> None:
    def stage_day(client: Client) -> None:
        client.execute(TRUNCATE_STAGING_SQL)
        client.execute(
            insert_rollup_sql(query_log_source()), day_query_parameters(day), settings=rollup_query_settings(context)
        )

    cluster.any_host_by_roles(stage_day, [ROLLUP_NODE_ROLE]).result()


def count_rollup_source_rows(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> int:
    [[source_rows]] = cluster.any_host_by_roles(
        lambda client: client.execute(
            count_rollup_source_rows_sql(query_log_source()),
            day_query_parameters(day),
            settings=rollup_query_settings(context),
        ),
        [ROLLUP_NODE_ROLE],
    ).result()
    return source_rows


def publish_day(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> None:
    if publish_staged_day(
        context,
        cluster,
        day,
        table=SHARDED_WAREHOUSE_OBJECT_READS_DAILY_TABLE,
        staging_table=SHARDED_WAREHOUSE_OBJECT_READS_DAILY_STAGING_TABLE,
        node_role=ROLLUP_NODE_ROLE,
    ):
        return
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


warehouse_object_reads_daily_schedule = build_catch_up_schedule(
    warehouse_object_reads_daily_job,
    start_date=ROLLUP_START_DATE,
    attempt_hours_utc=ATTEMPT_HOURS_UTC,
    catch_up_days=CATCH_UP_DAYS,
)

warehouse_object_reads_daily_overdue_sensor = build_overdue_sensor(
    warehouse_object_reads_daily_job,
    name="warehouse_object_reads_daily_overdue_sensor",
    owner=JobOwners.TEAM_DATA_MODELING,
    start_date=ROLLUP_START_DATE,
    attempt_hours_utc=ATTEMPT_HOURS_UTC,
    catch_up_days=CATCH_UP_DAYS,
    overdue_after_utc=OVERDUE_AFTER_UTC,
    check_interval_seconds=OVERDUE_CHECK_INTERVAL_SECONDS,
)
