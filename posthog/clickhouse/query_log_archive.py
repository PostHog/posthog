from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Buffer, Distributed, ReplicationScheme

QUERY_LOG_ARCHIVE_DATA_TABLE = "query_log_archive"


# ============================================================================
# v3 generation: one row per query chain
# ----------------------------------------------------------------------------
# system.query_log writes one row per (sub)query per node. The v3 data table
# collapses every row of a distributed query into one row keyed by the chain
# (initial_query_start_time, team_id, initial_query_id), with an
# AggregatingMergeTree merging the per-node rows: counters are summed, and
# the descriptive columns keep the initial query's value through max(). The
# MV zeroes the descriptive columns on non-initial rows so max() picks the
# initial row.
#
# The data table and the Buffer live only on OPS; the MV, the writable
# Distributed and the read Distributed live on every cluster. query_log_archive
# reads this table too.
# ============================================================================

SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE = "sharded_query_log_archive_v3"
QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE = "query_log_archive_v3_buffer"
WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE = "writable_query_log_archive_v3"
QUERY_LOG_ARCHIVE_V3_MV = "ops_query_log_archive_v3_mv"

_V3_PROFILE_EVENTS = (
    "SelectedRows",
    "SelectedBytes",
    "RealTimeMicroseconds",
    "OSCPUVirtualTimeMicroseconds",
    "UserTimeMicroseconds",
    "SystemTimeMicroseconds",
    "SelectedParts",
    "SelectedMarks",
    "NetworkReceiveBytes",
    "NetworkSendBytes",
    "ReadBufferFromFileDescriptorReadBytes",
    "WriteBufferFromFileDescriptorWriteBytes",
    "S3Clients",
    "S3DeleteObjects",
    "S3CopyObject",
    "S3ListObjects",
    "S3HeadObject",
    "S3GetObjectAttributes",
    "S3CreateMultipartUpload",
    "S3UploadPartCopy",
    "S3UploadPart",
    "S3AbortMultipartUpload",
    "S3CompleteMultipartUpload",
    "S3PutObject",
    "S3GetObject",
    "ReadBufferFromS3Bytes",
    "WriteBufferFromS3Bytes",
)

# T64 suits the counters, whose values sit far below the UInt64 range.
_V3_T64 = "CODEC(T64, Default)"
_V3_TTL_3_MONTHS = "TTL toDateTime(initial_query_start_time) + toIntervalMonth(3)"


def _v3_max(inner_type: str) -> str:
    return f"SimpleAggregateFunction(max, {inner_type})"


def _v3_sum(inner_type: str) -> str:
    return f"SimpleAggregateFunction(sum, {inner_type})"


# Each tuple is (name, type, storage clause). The storage clause applies only to the OPS data table:
# a Distributed or Buffer table stores nothing, so a codec or TTL there has no effect.
_V3_PHYSICAL_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("initial_query_start_time", "DateTime64(6, 'UTC')", ""),
    ("team_id", "Int64", ""),
    ("initial_query_id", "String", ""),
    ("is_initial_query", _v3_max("UInt8"), ""),
    ("hostname", _v3_max("LowCardinality(String)"), ""),
    ("user", _v3_max("LowCardinality(String)"), ""),
    (
        "type",
        _v3_max(
            "Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4)"
        ),
        "",
    ),
    ("event_time_microseconds", _v3_max("DateTime64(6, 'UTC')"), ""),
    ("query_duration_ms", _v3_max("UInt64"), ""),
    ("read_rows", _v3_sum("UInt64"), _V3_T64),
    ("read_bytes", _v3_sum("UInt64"), _V3_T64),
    ("written_rows", _v3_sum("UInt64"), _V3_T64),
    ("written_bytes", _v3_sum("UInt64"), _V3_T64),
    ("result_rows", _v3_sum("UInt64"), _V3_T64),
    ("result_bytes", _v3_sum("UInt64"), _V3_T64),
    ("memory_usage", _v3_max("UInt64"), _V3_T64),
    ("memory_usage_sum", _v3_sum("UInt64"), _V3_T64),
    ("peak_threads_usage", _v3_sum("UInt64"), _V3_T64),
    ("execution_count", _v3_sum("UInt64"), _V3_T64),
    ("current_database", _v3_max("LowCardinality(String)"), ""),
    ("query", _v3_max("String"), _V3_TTL_3_MONTHS),
    ("normalized_query_hash", _v3_max("UInt64"), ""),
    ("query_kind_by_root", _v3_max("Tuple(UInt8, String)"), ""),
    ("tables", _v3_max("Array(String)"), ""),
    ("exception_code", _v3_max("Int32"), ""),
    ("exception", _v3_max("String"), _V3_TTL_3_MONTHS),
    ("stack_trace", _v3_max("String"), ""),
    *((f"ProfileEvents_{event}", _v3_sum("UInt64"), _V3_T64) for event in _V3_PROFILE_EVENTS),
    ("lc_org_id", _v3_max("String"), ""),
    ("lc_user_id", _v3_max("Int64"), ""),
    ("lc_session_id", _v3_max("String"), ""),
    ("lc_is_impersonated", _v3_max("Bool"), ""),
    ("lc_workflow", _v3_max("LowCardinality(String)"), ""),
    ("lc_kind", _v3_max("LowCardinality(String)"), ""),
    ("lc_id", _v3_max("String"), ""),
    ("lc_route_id", _v3_max("String"), ""),
    ("lc_access_method", _v3_max("LowCardinality(String)"), ""),
    ("lc_api_key_label", _v3_max("String"), ""),
    ("lc_api_key_mask", _v3_max("String"), ""),
    ("lc_query_type", _v3_max("LowCardinality(String)"), ""),
    ("lc_product", _v3_max("LowCardinality(String)"), ""),
    ("lc_chargeable", _v3_max("Bool"), ""),
    ("lc_name", _v3_max("String"), ""),
    ("lc_request_name", _v3_max("String"), ""),
    ("lc_client_query_id", _v3_max("String"), ""),
    ("lc_dashboard_id", _v3_max("Int64"), ""),
    ("lc_insight_id", _v3_max("Int64"), ""),
    ("lc_cohort_id", _v3_max("Int64"), ""),
    ("lc_batch_export_id", _v3_max("String"), ""),
    ("lc_experiment_id", _v3_max("Int64"), ""),
    ("lc_experiment_feature_flag_key", _v3_max("String"), ""),
    ("lc_alert_config_id", _v3_max("String"), ""),
    ("lc_feature", _v3_max("LowCardinality(String)"), ""),
    ("lc_table_id", _v3_max("String"), ""),
    ("lc_warehouse_query", _v3_max("Bool"), ""),
    ("lc_person_on_events_mode", _v3_max("LowCardinality(String)"), ""),
    ("lc_service_name", _v3_max("LowCardinality(String)"), ""),
    ("lc_workload", _v3_max("LowCardinality(String)"), ""),
    ("lc_query__kind", _v3_max("LowCardinality(String)"), ""),
    ("lc_query__query", _v3_max("String"), _V3_TTL_3_MONTHS),
    ("lc_query", _v3_max("String"), _V3_TTL_3_MONTHS),
    ("lc_modifiers", _v3_max("String"), ""),
    ("lc_temporal__workflow_namespace", _v3_max("LowCardinality(String)"), ""),
    ("lc_temporal__workflow_type", _v3_max("LowCardinality(String)"), ""),
    ("lc_temporal__workflow_id", _v3_max("String"), ""),
    ("lc_temporal__workflow_run_id", _v3_max("String"), ""),
    ("lc_temporal__activity_type", _v3_max("LowCardinality(String)"), ""),
    ("lc_temporal__activity_id", _v3_max("String"), ""),
    ("lc_temporal__attempt", _v3_max("Int64"), ""),
    ("lc_dagster__job_name", _v3_max("LowCardinality(String)"), ""),
    ("lc_dagster__run_id", _v3_max("String"), ""),
    ("lc_dagster__owner", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_name", _v3_max("String"), ""),
    ("lc_experiment_metric_name", _v3_max("String"), ""),
    ("lc_experiment_execution_path", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_metric_type", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_funnel_order_type", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_exposures_path", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_metric_events_path", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_query_surface", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_precompute_table", _v3_max("String"), ""),
    ("lc_experiment_query_group_id", _v3_max("String"), ""),
    ("lc_experiment_precompute_skip_reason", _v3_max("LowCardinality(String)"), ""),
    ("lc_experiment_scan_date_from", _v3_max("String"), ""),
    ("lc_experiment_scan_date_to", _v3_max("String"), ""),
    ("lc_precompute_window_start", _v3_max("String"), ""),
    ("lc_precompute_window_end", _v3_max("String"), ""),
    ("lc_plan_fingerprint", _v3_max("String"), ""),
    ("lc_estimated_rows", _v3_max("Int64"), ""),
    ("lc_estimated_bytes", _v3_max("Int64"), ""),
)

# Read-time aliases that keep the column names of the earlier generations, so existing readers of
# query_log_archive (query_id, event_date, ProfileEvents[...], ...) keep working on the aggregate.
_V3_ALIAS_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("query_id", "String", "initial_query_id"),
    ("event_time", "DateTime('UTC')", "toDateTime(event_time_microseconds)"),
    ("event_date", "Date", "toDate(event_time_microseconds)"),
    ("query_start_time", "DateTime('UTC')", "toDateTime(initial_query_start_time)"),
    ("query_start_time_microseconds", "DateTime64(6, 'UTC')", "initial_query_start_time"),
    ("query_kind", "LowCardinality(String)", "tupleElement(query_kind_by_root, 2)"),
    ("formatted_query", "String", "''"),
    ("query_shape", "String", "normalizeQuery(query)"),
    ("hogql_shape", "String", "normalizeQuery(lc_query__query)"),
    ("exception_name", "String", "errorCodeToName(exception_code)"),
    (
        "ProfileEvents",
        "Map(String, UInt64)",
        "map({})".format(", ".join(f"'{event}', ProfileEvents_{event}" for event in _V3_PROFILE_EVENTS)),
    ),
)

_V3_INDEXES = (
    "INDEX initial_query_start_time_minmax initial_query_start_time TYPE minmax GRANULARITY 1",
    "INDEX event_date_minmax toDate(event_time_microseconds) TYPE minmax GRANULARITY 1",
    "INDEX event_time_minmax toDateTime(event_time_microseconds) TYPE minmax GRANULARITY 1",
)


def SHARDED_QUERY_LOG_ARCHIVE_V3_ENGINE():
    # The zoo path keeps the "_by_chain" suffix it has in production.
    return AggregatingMergeTree(
        f"{SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE}_by_chain", replication_scheme=ReplicationScheme.SHARDED
    )


def SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE_SQL():
    columns = [" ".join(filter(None, (name, type_, storage))) for name, type_, storage in _V3_PHYSICAL_COLUMNS]
    columns += [f"{name} {type_} ALIAS {expr}" for name, type_, expr in _V3_ALIAS_COLUMNS]
    columns += list(_V3_INDEXES)
    return """CREATE TABLE IF NOT EXISTS {table_name} (
    {columns}
) ENGINE = {engine}
PARTITION BY toYYYYMM(initial_query_start_time)
ORDER BY (toStartOfHour(initial_query_start_time), team_id, initial_query_start_time, initial_query_id)""".format(
        table_name=SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE,
        columns=",\n    ".join(columns),
        engine=SHARDED_QUERY_LOG_ARCHIVE_V3_ENGINE(),
    )


def _v3_plain_table_sql(table_name: str, engine: object, include_aliases: bool) -> str:
    # A Distributed or Buffer table declares the alias names as plain columns: the data table computes them.
    columns = [f"{name} {type_}" for name, type_, _ in _V3_PHYSICAL_COLUMNS]
    if include_aliases:
        columns += [f"{name} {type_}" for name, type_, _ in _V3_ALIAS_COLUMNS]
    return "CREATE TABLE IF NOT EXISTS {table_name} (\n    {columns}\n) ENGINE = {engine}".format(
        table_name=table_name, columns=",\n    ".join(columns), engine=engine
    )


def DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(cluster=None):
    """Distributed read table (query_log_archive) over the v3 data table, created on every cluster."""
    return _v3_plain_table_sql(
        QUERY_LOG_ARCHIVE_DATA_TABLE,
        Distributed(data_table=SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE, cluster=cluster or settings.CLICKHOUSE_OPS_CLUSTER),
        include_aliases=True,
    )


def QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL():
    """Buffer on OPS in front of the v3 data table."""
    return _v3_plain_table_sql(
        QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE,
        Buffer(
            destination_table=SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE,
            num_layers=16,
            min_time=10,
            max_time=60,
            min_rows=10_000,
            max_rows=1_000_000,
            min_bytes=10_000_000,
            max_bytes=100_000_000,
        ),
        include_aliases=False,
    )


def WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE_SQL(cluster=None):
    """Distributed write table on every cluster, pointing at the OPS v3 Buffer."""
    return _v3_plain_table_sql(
        WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE,
        Distributed(data_table=QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, cluster=cluster or settings.CLICKHOUSE_OPS_CLUSTER),
        include_aliases=False,
    )


# log_comment is parsed once into a typed tuple. A key that is absent reads as the type's default.
_V3_LOG_COMMENT_TUPLE = (
    "Tuple("
    "team_id Int64, org_id String, user_id Int64, session_id String, is_impersonated Bool, "
    "workflow String, kind String, id String, route_id String, access_method String, "
    "api_key_label String, api_key_mask String, query_type String, product String, chargeable Bool, "
    "name String, request_name String, client_query_id String, dashboard_id Int64, insight_id Int64, "
    "cohort_id Int64, batch_export_id String, experiment_id Int64, experiment_feature_flag_key String, "
    "alert_config_id String, feature String, table_id String, warehouse_query Bool, "
    "person_on_events_mode String, service_name String, workload String, "
    "experiment_name String, experiment_metric_name String, experiment_execution_path String, "
    "experiment_metric_type String, experiment_funnel_order_type String, experiment_exposures_path String, "
    "experiment_metric_events_path String, experiment_query_surface String, experiment_precompute_table String, "
    "experiment_query_group_id String, experiment_precompute_skip_reason String, "
    "experiment_scan_date_from String, experiment_scan_date_to String, "
    "precompute_window_start String, precompute_window_end String, "
    "plan_fingerprint String, estimated_rows Int64, estimated_bytes Int64, "
    "temporal Tuple(workflow_namespace String, workflow_type String, workflow_id String, "
    "workflow_run_id String, activity_type String, activity_id String, attempt Int64), "
    "dagster Tuple(job_name String, run_id String, tags Tuple(owner String)), "
    "query Tuple(kind String, query String, source Tuple(kind String, query String))"
    ")"
)

# Profile events kept from the initial query's row only. The other events are summed over every node.
_V3_INITIAL_ONLY_PROFILE_EVENTS = ("SelectedRows", "SelectedBytes")

_V3_LOG_COMMENT_FIELDS = (
    "org_id",
    "user_id",
    "session_id",
    "is_impersonated",
    "workflow",
    "kind",
    "id",
    "route_id",
    "access_method",
    "api_key_label",
    "api_key_mask",
    "query_type",
    "product",
    "chargeable",
    "name",
    "request_name",
    "client_query_id",
    "dashboard_id",
    "insight_id",
    "cohort_id",
    "batch_export_id",
    "experiment_id",
    "experiment_feature_flag_key",
    "alert_config_id",
    "feature",
    "table_id",
    "warehouse_query",
    "person_on_events_mode",
    "service_name",
    "workload",
)

_V3_LOG_COMMENT_TRAILING_FIELDS = (
    "experiment_name",
    "experiment_metric_name",
    "experiment_execution_path",
    "experiment_metric_type",
    "experiment_funnel_order_type",
    "experiment_exposures_path",
    "experiment_metric_events_path",
    "experiment_query_surface",
    "experiment_precompute_table",
    "experiment_query_group_id",
    "experiment_precompute_skip_reason",
    "experiment_scan_date_from",
    "experiment_scan_date_to",
    "precompute_window_start",
    "precompute_window_end",
    "plan_fingerprint",
    "estimated_rows",
    "estimated_bytes",
)


def _v3_profile_event_select(event: str) -> str:
    value = f"ql.ProfileEvents['{event}']"
    if event in _V3_INITIAL_ONLY_PROFILE_EVENTS:
        value = f"if(ql.is_initial_query, {value}, 0)"
    return f"{value} AS ProfileEvents_{event}"


MV_SELECT_SQL_V3 = """
WITH JSONExtract(ql.log_comment, '{log_comment_tuple}') AS lc
SELECT
    if(empty(ql.initial_query_id), ql.query_start_time_microseconds, ql.initial_query_start_time_microseconds) AS initial_query_start_time,
    lc.team_id AS team_id,
    if(empty(ql.initial_query_id), ql.query_id, ql.initial_query_id) AS initial_query_id,
    ql.is_initial_query AS is_initial_query,
    if(ql.is_initial_query, ql.hostname, '') AS hostname,
    ql.user AS user,
    ql.type AS type,
    ql.event_time_microseconds AS event_time_microseconds,
    if(ql.is_initial_query, ql.query_duration_ms, 0) AS query_duration_ms,
    if(ql.is_initial_query, ql.read_rows, 0) AS read_rows,
    if(ql.is_initial_query, ql.read_bytes, 0) AS read_bytes,
    if(ql.is_initial_query, ql.written_rows, 0) AS written_rows,
    if(ql.is_initial_query, ql.written_bytes, 0) AS written_bytes,
    if(ql.is_initial_query, ql.result_rows, 0) AS result_rows,
    if(ql.is_initial_query, ql.result_bytes, 0) AS result_bytes,
    ql.memory_usage AS memory_usage,
    ql.memory_usage AS memory_usage_sum,
    ql.peak_threads_usage AS peak_threads_usage,
    1 AS execution_count,
    ql.current_database AS current_database,
    if(ql.is_initial_query, ql.query, '') AS query,
    if(ql.is_initial_query, ql.normalized_query_hash, 0) AS normalized_query_hash,
    tuple(ql.is_initial_query, ql.query_kind) AS query_kind_by_root,
    if(ql.is_initial_query, ql.tables, []) AS tables,
    if(ql.is_initial_query, ql.exception_code, 0) AS exception_code,
    if(ql.is_initial_query, ql.exception, '') AS exception,
    if(ql.is_initial_query, ql.stack_trace, '') AS stack_trace,
    {profile_events},
    {log_comment_fields},
    if(notEmpty(lc.query.source.kind), lc.query.source.kind, lc.query.kind) AS lc_query__kind,
    if(ql.is_initial_query, if(notEmpty(lc.query.source.kind), lc.query.source.query, lc.query.query), '') AS lc_query__query,
    if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'query'), '') AS lc_query,
    if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'modifiers'), '') AS lc_modifiers,
    lc.temporal.workflow_namespace AS lc_temporal__workflow_namespace,
    lc.temporal.workflow_type AS lc_temporal__workflow_type,
    lc.temporal.workflow_id AS lc_temporal__workflow_id,
    lc.temporal.workflow_run_id AS lc_temporal__workflow_run_id,
    lc.temporal.activity_type AS lc_temporal__activity_type,
    lc.temporal.activity_id AS lc_temporal__activity_id,
    lc.temporal.attempt AS lc_temporal__attempt,
    lc.dagster.job_name AS lc_dagster__job_name,
    lc.dagster.run_id AS lc_dagster__run_id,
    lc.dagster.tags.owner AS lc_dagster__owner,
    {log_comment_trailing_fields}
FROM system.query_log AS ql
WHERE ql.type != 'QueryStart'
""".format(
    log_comment_tuple=_V3_LOG_COMMENT_TUPLE,
    profile_events=",\n    ".join(_v3_profile_event_select(event) for event in _V3_PROFILE_EVENTS),
    log_comment_fields=",\n    ".join(f"lc.{field} AS lc_{field}" for field in _V3_LOG_COMMENT_FIELDS),
    log_comment_trailing_fields=",\n    ".join(
        f"lc.{field} AS lc_{field}" for field in _V3_LOG_COMMENT_TRAILING_FIELDS
    ),
)


def QUERY_LOG_ARCHIVE_V3_MV_SQL():
    # The explicit column list makes ClickHouse cast the SELECT output to the aggregate state types.
    return "CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}\nTO {dest_table} (\n    {columns}\n)\nAS {select_sql}".format(
        view_name=QUERY_LOG_ARCHIVE_V3_MV,
        dest_table=WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE,
        columns=",\n    ".join(f"{name} {type_}" for name, type_, _ in _V3_PHYSICAL_COLUMNS),
        select_sql=MV_SELECT_SQL_V3,
    )
