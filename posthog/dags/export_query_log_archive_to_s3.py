import dagster
import pydantic
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.resources import OpsClickhouseClusterResource

SOURCE_TABLE = "posthog.query_log_archive"

KEEP_COLUMNS = (
    "hostname",
    "user",
    "query_id",
    "initial_query_id",
    "is_initial_query",
    "type",
    "event_date",
    "event_time",
    "event_time_microseconds",
    "query_start_time",
    "query_start_time_microseconds",
    "query_duration_ms",
    "read_rows",
    "read_bytes",
    "written_rows",
    "written_bytes",
    "result_rows",
    "result_bytes",
    "memory_usage",
    "peak_threads_usage",
    "current_database",
    "normalized_query_hash",
    "query_kind",
    "exception_code",
    "exception_name",
    "team_id",
    "ProfileEvents_RealTimeMicroseconds",
    "ProfileEvents_OSCPUVirtualTimeMicroseconds",
    "ProfileEvents_S3Clients",
    "ProfileEvents_S3DeleteObjects",
    "ProfileEvents_S3CopyObject",
    "ProfileEvents_S3ListObjects",
    "ProfileEvents_S3HeadObject",
    "ProfileEvents_S3GetObjectAttributes",
    "ProfileEvents_S3CreateMultipartUpload",
    "ProfileEvents_S3UploadPartCopy",
    "ProfileEvents_S3UploadPart",
    "ProfileEvents_S3AbortMultipartUpload",
    "ProfileEvents_S3CompleteMultipartUpload",
    "ProfileEvents_S3PutObject",
    "ProfileEvents_S3GetObject",
    "ProfileEvents_ReadBufferFromS3Bytes",
    "ProfileEvents_WriteBufferFromS3Bytes",
    "lc_workflow",
    "lc_kind",
    "lc_id",
    "lc_route_id",
    "lc_access_method",
    "lc_api_key_mask",
    "lc_query_type",
    "lc_product",
    "lc_chargeable",
    "lc_name",
    "lc_request_name",
    "lc_client_query_id",
    "lc_org_id",
    "lc_user_id",
    "lc_is_impersonated",
    "lc_session_id",
    "lc_dashboard_id",
    "lc_insight_id",
    "lc_cohort_id",
    "lc_batch_export_id",
    "lc_experiment_id",
    "lc_alert_config_id",
    "lc_feature",
    "lc_table_id",
    "lc_warehouse_query",
    "lc_person_on_events_mode",
    "lc_service_name",
    "lc_workload",
    "lc_query__kind",
    "lc_temporal__workflow_namespace",
    "lc_temporal__workflow_type",
    "lc_temporal__workflow_id",
    "lc_temporal__workflow_run_id",
    "lc_temporal__activity_type",
    "lc_temporal__activity_id",
    "lc_temporal__attempt",
    "lc_dagster__job_name",
    "lc_dagster__run_id",
    "lc_dagster__owner",
    "lc_modifiers",
)

# ClickHouse folds leaf read_rows/read_bytes into the initial row via progress packets, but
# ProfileEvents and memory_usage stay per-host, so each initial row gets its leaves rolled up
# here where the per-query-id join is cheap; consumers cannot afford it at read time.
LEAF_SUM_COLUMNS = tuple(column for column in KEEP_COLUMNS if column.startswith("ProfileEvents_"))

ONE_GB = 1024 * 1024 * 1024


class QueryLogArchiveExportConfig(dagster.Config):
    max_threads: int = pydantic.Field(
        default=12,
        ge=1,
        description="ClickHouse max_threads for the export scan. Must be ≥ 1 (0 means auto/all-cores in ClickHouse and will re-enable the OOM risk).",
    )
    s3_prefix: str = "query_log_archive"
    s3_bucket: str = settings.QUERY_LOG_ARCHIVE_EXPORT_S3_BUCKET


daily_partitions = dagster.DailyPartitionsDefinition(
    start_date="2026-01-01",
    timezone="UTC",
    # query_log_archive only retains a few weeks on the source, so older partitions will export
    # empty; that is harmless (idempotent overwrite of one key per day).
)


@dagster.op
def export_query_log_archive_day(
    context: dagster.OpExecutionContext,
    config: QueryLogArchiveExportConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> str:
    day = context.partition_key  # "YYYY-MM-DD"
    if not config.s3_bucket:
        # No export bucket for this region (e.g. dev); nothing to write to.
        context.log.warning(f"No query_log_archive export bucket configured for this deployment; skipping {day}")
        return f"Skipped {day} (no export bucket)"

    s3_url = f"https://{config.s3_bucket}.s3.amazonaws.com/{config.s3_prefix}/day={day}/data.parquet"
    columns = ",\n    ".join(f"`{column}`" for column in KEEP_COLUMNS)
    leaf_sums = ",\n        ".join(f"sum(`{column}`) AS `leaf_{column}`" for column in LEAF_SUM_COLUMNS)
    leaf_columns = ",\n    ".join(f"`leaf_{column}`" for column in LEAF_SUM_COLUMNS)
    # Leaf rows of a query straddling midnight land on the next event_date, hence the two-day window.
    # The rollup keeps only parents present in the day's initial rows so its join hash table stays
    # small enough to hold in memory; spilling the join to disk instead OOMs or times out on the
    # read-back of the wide probe rows. Parents are matched on cityHash64(query_id) rather than the
    # 36-char id string, shrinking the IN set and hash table keys 5x; a 64-bit collision would merge
    # one pair of queries' rollups (~once per 160 years of daily exports).
    query = f"""
INSERT INTO FUNCTION s3('{s3_url}', 'Parquet')
SELECT
    {columns},
    normalizeQuery(query) AS query_shape,
    normalizeQuery(lc_query__query) AS hogql_shape,
    leaf_count,
    leaf_memory_usage_max,
    {leaf_columns}
FROM
(
    SELECT
        {columns},
        cityHash64(query_id) AS parent_key,
        query,
        lc_query__query
    FROM {SOURCE_TABLE}
    WHERE event_date = toDate('{day}') AND is_initial_query
) AS initial_rows
LEFT JOIN
(
    SELECT
        cityHash64(initial_query_id) AS leaf_parent_key,
        count() AS leaf_count,
        max(memory_usage) AS leaf_memory_usage_max,
        {leaf_sums}
    FROM {SOURCE_TABLE}
    WHERE event_date >= toDate('{day}') AND event_date <= toDate('{day}') + 1 AND NOT is_initial_query
        AND cityHash64(initial_query_id) IN (
            SELECT cityHash64(query_id) FROM {SOURCE_TABLE} WHERE event_date = toDate('{day}') AND is_initial_query
        )
    GROUP BY leaf_parent_key
) AS leaf ON initial_rows.parent_key = leaf.leaf_parent_key
SETTINGS s3_truncate_on_insert = 1, max_threads = {config.max_threads},
    join_algorithm = 'hash', max_bytes_before_external_group_by = 2000000000,
    min_insert_block_size_rows = 65536, min_insert_block_size_bytes = 134217728,
    output_format_parquet_row_group_size = 131072, output_format_parquet_row_group_size_bytes = 134217728
"""

    def run(client: Client) -> str:
        [[hostname]] = client.execute("SELECT hostName()")
        context.log.info(f"Exporting {day} -> {s3_url} on OPS host {hostname}")
        client.execute(query, settings=settings_with_log_comment(context))
        return hostname

    # Run once on a single OPS host so the two OPS replicas don't race to write the same S3 key.
    hostname = cluster.any_host_by_role(run, NodeRole.OPS).result()
    context.log.info(f"Exported {day} on {hostname}")
    return f"Exported {day}"


@dagster.job(
    partitions_def=daily_partitions,
    resource_defs={
        "cluster": OpsClickhouseClusterResource(max_execution_time=2 * 60 * 60, max_memory_usage=20 * ONE_GB)
    },
    tags={
        "owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value,
        "query_log_archive_backfill_concurrency": "query_log_archive_v1",
    },
)
def export_query_log_archive_to_s3():
    export_query_log_archive_day()


query_log_archive_export_schedule = dagster.build_schedule_from_partitioned_job(
    export_query_log_archive_to_s3,
    hour_of_day=6,
    minute_of_hour=0,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
