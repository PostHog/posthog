# Curated JSON subset of log_comment. Keys not hinted here are still kept as
# dynamic paths (bounded by max_dynamic_paths) UNLESS listed in SKIP. The SKIP
# list drops PII (user_email, http_*) and bulky objects (query_settings, timings,
# filter, hogql_features) so they never reach the archive. The `query` and
# `modifiers` subtrees are intentionally NOT skipped so the lc_query* / lc_modifiers
# aliases can read them back.
LOG_COMMENT_JSON_TYPE = """JSON(
        max_dynamic_paths = 256,
        team_id Int64,
        user_id Int64,
        org_id String,
        session_id String,
        access_method LowCardinality(String),
        api_key_label String,
        api_key_mask String,
        workflow LowCardinality(String),
        kind LowCardinality(String),
        id String,
        route_id String,
        query_type LowCardinality(String),
        product LowCardinality(String),
        chargeable Bool,
        name String,
        request_name String,
        client_query_id String,
        is_impersonated Bool,
        dashboard_id Int64,
        insight_id Int64,
        cohort_id Int64,
        batch_export_id String,
        experiment_id Int64,
        experiment_feature_flag_key String,
        alert_config_id String,
        feature LowCardinality(String),
        table_id String,
        warehouse_query Bool,
        person_on_events_mode LowCardinality(String),
        service_name String,
        workload LowCardinality(String),
        `temporal.workflow_namespace` String,
        `temporal.workflow_type` String,
        `temporal.workflow_id` String,
        `temporal.workflow_run_id` String,
        `temporal.activity_type` String,
        `temporal.activity_id` String,
        `temporal.attempt` Int64,
        `dagster.job_name` String,
        `dagster.run_id` String,
        `dagster.tags.owner` String,
        SKIP user_email,
        SKIP query_settings,
        SKIP timings,
        SKIP `filter`,
        SKIP hogql_features,
        SKIP http_referer,
        SKIP http_user_agent,
        SKIP http_request_id,
        SKIP cache_key
    )"""

# Real columns copied verbatim from system.query_log, plus the physical team_id
# (it is part of the sort key so it cannot be an alias), the JSON log_comment and
# the raw ProfileEvents map. These are exactly the columns the MV inserts.
_QUERY_LOG_ARCHIVE_PHYSICAL_COLUMNS = """
    hostname                              LowCardinality(String),
    user                                  LowCardinality(String),
    query_id                              String,
    initial_query_id                      String,
    is_initial_query                      UInt8,
    type                                  Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4),

    event_date                            Date,
    event_time                            DateTime,
    event_time_microseconds               DateTime64(6),
    query_start_time                      DateTime,
    query_start_time_microseconds         DateTime64(6),
    query_duration_ms                     UInt64,

    read_rows                             UInt64,
    read_bytes                            UInt64,
    written_rows                          UInt64,
    written_bytes                         UInt64,
    result_rows                           UInt64,
    result_bytes                          UInt64,
    memory_usage                          UInt64,
    peak_threads_usage                    UInt64,

    current_database                      LowCardinality(String),
    query                                 String,
    formatted_query                       String,
    normalized_query_hash                 UInt64,
    query_kind                            LowCardinality(String),

    exception_code                        Int32,
    exception                             String,
    stack_trace                           String,

    team_id                               Int64,
    log_comment                           {log_comment_type},
    ProfileEvents                         Map(String, UInt64)""".format(log_comment_type=LOG_COMMENT_JSON_TYPE)

# HogQL cost planner tags (posthog/hogql/cost/). These keys have no type hint in LOG_COMMENT_JSON_TYPE, so the
# JSON column keeps them as Dynamic paths that read as NULL when absent. dynamicElement extracts the typed value
# and ifNull gives the same '' / 0 default the hinted lc_* columns have. It is the function form of the `.:Type`
# subcolumn syntax, which the HCL introspection parser (hclexp) cannot read back from SHOW CREATE TABLE.
_COST_PLANNER_ALIAS_COLUMNS = (
    "lc_plan_fingerprint String ALIAS ifNull(dynamicElement(log_comment.plan_fingerprint, 'String'), '')",
    "lc_estimated_rows Int64 ALIAS ifNull(dynamicElement(log_comment.estimated_rows, 'Int64'), 0)",
    "lc_estimated_bytes Int64 ALIAS ifNull(dynamicElement(log_comment.estimated_bytes, 'Int64'), 0)",
)

# Read-time aliases. lc_* read the curated JSON subset; ProfileEvents_* read the
# raw map; exception_name keeps its derived form. The lc_query* / lc_modifiers
# aliases reproduce the previous MV logic (source preference + is_initial_query
# gating) against the serialized JSON.
_QUERY_LOG_ARCHIVE_ALIAS_COLUMNS = """
    exception_name String ALIAS errorCodeToName(exception_code),

    ProfileEvents_RealTimeMicroseconds Int64 ALIAS ProfileEvents['RealTimeMicroseconds'],
    ProfileEvents_OSCPUVirtualTimeMicroseconds Int64 ALIAS ProfileEvents['OSCPUVirtualTimeMicroseconds'],
    ProfileEvents_S3Clients Int64 ALIAS ProfileEvents['S3Clients'],
    ProfileEvents_S3DeleteObjects Int64 ALIAS ProfileEvents['S3DeleteObjects'],
    ProfileEvents_S3CopyObject Int64 ALIAS ProfileEvents['S3CopyObject'],
    ProfileEvents_S3ListObjects Int64 ALIAS ProfileEvents['S3ListObjects'],
    ProfileEvents_S3HeadObject Int64 ALIAS ProfileEvents['S3HeadObject'],
    ProfileEvents_S3GetObjectAttributes Int64 ALIAS ProfileEvents['S3GetObjectAttributes'],
    ProfileEvents_S3CreateMultipartUpload Int64 ALIAS ProfileEvents['S3CreateMultipartUpload'],
    ProfileEvents_S3UploadPartCopy Int64 ALIAS ProfileEvents['S3UploadPartCopy'],
    ProfileEvents_S3UploadPart Int64 ALIAS ProfileEvents['S3UploadPart'],
    ProfileEvents_S3AbortMultipartUpload Int64 ALIAS ProfileEvents['S3AbortMultipartUpload'],
    ProfileEvents_S3CompleteMultipartUpload Int64 ALIAS ProfileEvents['S3CompleteMultipartUpload'],
    ProfileEvents_S3PutObject Int64 ALIAS ProfileEvents['S3PutObject'],
    ProfileEvents_S3GetObject Int64 ALIAS ProfileEvents['S3GetObject'],
    ProfileEvents_ReadBufferFromS3Bytes Int64 ALIAS ProfileEvents['ReadBufferFromS3Bytes'],
    ProfileEvents_WriteBufferFromS3Bytes Int64 ALIAS ProfileEvents['WriteBufferFromS3Bytes'],

    lc_workflow LowCardinality(String) ALIAS log_comment.workflow,
    lc_kind LowCardinality(String) ALIAS log_comment.kind,
    lc_id String ALIAS log_comment.id::String,
    lc_route_id String ALIAS log_comment.route_id::String,
    lc_access_method LowCardinality(String) ALIAS log_comment.access_method,
    lc_api_key_label String ALIAS log_comment.api_key_label::String,
    lc_api_key_mask String ALIAS log_comment.api_key_mask::String,
    lc_query_type LowCardinality(String) ALIAS log_comment.query_type,
    lc_product LowCardinality(String) ALIAS log_comment.product,
    lc_chargeable Bool ALIAS log_comment.chargeable,
    lc_name String ALIAS log_comment.name::String,
    lc_request_name String ALIAS log_comment.request_name::String,
    lc_client_query_id String ALIAS log_comment.client_query_id::String,
    lc_org_id String ALIAS log_comment.org_id::String,
    lc_user_id Int64 ALIAS log_comment.user_id,
    lc_is_impersonated Bool ALIAS log_comment.is_impersonated,
    lc_session_id String ALIAS log_comment.session_id::String,
    lc_dashboard_id Int64 ALIAS log_comment.dashboard_id,
    lc_insight_id Int64 ALIAS log_comment.insight_id,
    lc_cohort_id Int64 ALIAS log_comment.cohort_id,
    lc_batch_export_id String ALIAS log_comment.batch_export_id::String,
    lc_experiment_id Int64 ALIAS log_comment.experiment_id,
    lc_experiment_feature_flag_key String ALIAS log_comment.experiment_feature_flag_key::String,
    lc_alert_config_id String ALIAS log_comment.alert_config_id::String,
    lc_feature LowCardinality(String) ALIAS log_comment.feature,
    lc_table_id String ALIAS log_comment.table_id::String,
    lc_warehouse_query Bool ALIAS log_comment.warehouse_query,
    lc_person_on_events_mode LowCardinality(String) ALIAS log_comment.person_on_events_mode,
    lc_service_name String ALIAS log_comment.service_name::String,
    lc_workload LowCardinality(String) ALIAS log_comment.workload,

    lc_query__kind LowCardinality(String) ALIAS if(JSONHas(toString(log_comment), 'query', 'source'),
        JSONExtractString(toString(log_comment), 'query', 'source', 'kind'),
        JSONExtractString(toString(log_comment), 'query', 'kind')),
    lc_query__query String ALIAS multiIf(not is_initial_query, '',
        JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'query'),
        JSONExtractString(toString(log_comment), 'query', 'query')),
    lc_query String ALIAS if(is_initial_query, JSONExtractRaw(toString(log_comment), 'query'), ''),

    lc_temporal__workflow_namespace String ALIAS log_comment.`temporal.workflow_namespace`::String,
    lc_temporal__workflow_type String ALIAS log_comment.`temporal.workflow_type`::String,
    lc_temporal__workflow_id String ALIAS log_comment.`temporal.workflow_id`::String,
    lc_temporal__workflow_run_id String ALIAS log_comment.`temporal.workflow_run_id`::String,
    lc_temporal__activity_type String ALIAS log_comment.`temporal.activity_type`::String,
    lc_temporal__activity_id String ALIAS log_comment.`temporal.activity_id`::String,
    lc_temporal__attempt Int64 ALIAS log_comment.`temporal.attempt`,

    lc_dagster__job_name String ALIAS log_comment.`dagster.job_name`::String,
    lc_dagster__run_id String ALIAS log_comment.`dagster.run_id`::String,
    lc_dagster__owner String ALIAS log_comment.`dagster.tags.owner`::String,

    lc_modifiers String ALIAS if(is_initial_query, JSONExtractRaw(toString(log_comment), 'modifiers'), ''),

    {cost_planner_aliases}""".format(cost_planner_aliases=",\n    ".join(_COST_PLANNER_ALIAS_COLUMNS))

_QUERY_LOG_ARCHIVE_OPS_TABLE_CLAUSES = """
PARTITION BY toYYYYMM(event_date)
ORDER BY (team_id, event_date, event_time, query_id)
PRIMARY KEY (team_id, event_date, event_time, query_id)"""


def QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(
    table_name, engine, include_aliases=True, include_table_clauses=True, settings=None
):
    """JSON-backed query_log_archive table.

    include_aliases=True for the data table and read tables (exposes lc_* / ProfileEvents_*).
    include_aliases=False for the writable distributed table (physical, insertable columns only).
    """
    columns = _QUERY_LOG_ARCHIVE_PHYSICAL_COLUMNS
    if include_aliases:
        columns = f"{columns},\n{_QUERY_LOG_ARCHIVE_ALIAS_COLUMNS}"
    return "CREATE TABLE IF NOT EXISTS {table_name} (\n{columns}\n) ENGINE = {engine}{table_clauses} {settings}".format(
        table_name=table_name,
        columns=columns,
        engine=engine,
        table_clauses=_QUERY_LOG_ARCHIVE_OPS_TABLE_CLAUSES if include_table_clauses else "",
        settings=settings if settings else "",
    )
