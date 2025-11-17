from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme

QUERY_LOG_ARCHIVE_DATA_TABLE = "query_log_archive"
QUERY_LOG_ARCHIVE_MV = "query_log_archive_mv"


def QUERY_LOG_ARCHIVE_TABLE_ENGINE_NEW():
    return MergeTreeEngine("query_log_archive_new", replication_scheme=ReplicationScheme.REPLICATED)


CREATE_QUERY_LOG_ARCHIVE_BASE_TABLE = """
CREATE TABLE IF NOT EXISTS {table_name} (
    hostname                              LowCardinality(String), -- comment 'Hostname of the server executing the query.',
    user                                  LowCardinality(String), -- comment 'Name of the user who initiated the current query.',
    query_id                              String, -- comment 'ID of the query.',
    type                                  Enum8('QueryStart' = 1, 'QueryFinish' = 2, 'ExceptionBeforeStart' = 3, 'ExceptionWhileProcessing' = 4), -- comment 'Type of an event that occurred when executing the query.',

    event_date                            Date, -- comment 'Query starting date.',
    event_time                            DateTime, -- comment 'Query starting time.',
    event_time_microseconds               DateTime64(6), -- comment 'Query starting time with microseconds precision.',
    query_start_time                      DateTime, -- comment 'Start time of query execution.',
    query_start_time_microseconds         DateTime64(6), -- comment 'Start time of query execution with microsecond precision.',
    query_duration_ms                     UInt64, -- comment 'Duration of query execution in milliseconds.',

    read_rows                             UInt64, -- comment 'Total number of rows read from all tables and table functions participated in query. It includes usual subqueries, subqueries for IN and JOIN. For distributed queries read_rows includes the total number of rows read at all replicas. Each replica sends it''s read_rows value, and the server-initiator of the query summarizes all received and local values. The cache volumes do not affect this value.',
    read_bytes                            UInt64, -- comment 'Total number of bytes read from all tables and table functions participated in query. It includes usual subqueries, subqueries for IN and JOIN. For distributed queries read_bytes includes the total number of rows read at all replicas. Each replica sends it''s read_bytes value, and the server-initiator of the query summarizes all received and local values. The cache volumes do not affect this value.',
    written_rows                          UInt64, -- comment 'For INSERT queries, the number of written rows. For other queries, the column value is 0.',
    written_bytes                         UInt64, -- comment 'For INSERT queries, the number of written bytes (uncompressed). For other queries, the column value is 0.',
    result_rows                           UInt64, -- comment 'Number of rows in a result of the SELECT query, or a number of rows in the INSERT query.',
    result_bytes                          UInt64, -- comment 'RAM volume in bytes used to store a query result.',
    memory_usage                          UInt64, -- comment 'Memory consumption by the query.',
    peak_threads_usage                    UInt64, -- comment 'Maximum count of simultaneous threads executing the query.',

    current_database                      LowCardinality(String), -- comment 'Name of the current database.',
    query                                 String, -- comment ' Query string.',
    formatted_query                       String, -- comment 'Formatted query string.',
    normalized_query_hash                 UInt64, -- comment 'A numeric hash value, such as it is identical for queries differ only by values of literals.',
    query_kind                            LowCardinality(String), -- comment 'Type of the query.',

    exception_code                        Int32, -- comment 'Code of an exception.',
    exception_name                        String ALIAS errorCodeToName(exception_code), -- comment 'Name of an exception.',
    exception                             String, -- comment 'Exception message.',
    stack_trace                           String, -- comment 'Stack trace. An empty string, if the query was completed successfully.',

    -- the above columns are copied directly from system.query_log
    ProfileEvents_RealTimeMicroseconds Int64, -- comment 'ProfileEvents[RealTimeMicroseconds]',
    ProfileEvents_OSCPUVirtualTimeMicroseconds Int64, -- comment 'ProfileEvents[OSCPUVirtualTimeMicroseconds]',

    -- s3 stats in query_log.ProfileEvents
    ProfileEvents_S3Clients Int64, -- comment 'ProfileEvents[S3Clients]'
    ProfileEvents_S3DeleteObjects Int64, -- comment 'ProfileEvents[S3DeleteObjects]'
    ProfileEvents_S3CopyObject Int64, -- comment 'ProfileEvents[S3CopyObject]'
    ProfileEvents_S3ListObjects Int64, -- comment 'ProfileEvents[S3ListObjects]'
    ProfileEvents_S3HeadObject Int64, -- comment 'ProfileEvents[S3HeadObject]'
    ProfileEvents_S3GetObjectAttributes Int64, -- comment 'ProfileEvents[S3GetObjectAttributes]'
    ProfileEvents_S3CreateMultipartUpload Int64, -- comment 'ProfileEvents[S3CreateMultipartUpload]'
    ProfileEvents_S3UploadPartCopy Int64, -- comment 'ProfileEvents[S3UploadPartCopy]'
    ProfileEvents_S3UploadPart Int64, -- comment 'ProfileEvents[S3UploadPart]'
    ProfileEvents_S3AbortMultipartUpload Int64, -- comment 'ProfileEvents[S3AbortMultipartUpload]'
    ProfileEvents_S3CompleteMultipartUpload Int64, -- comment 'ProfileEvents[S3CompleteMultipartUpload]'
    ProfileEvents_S3PutObject Int64, -- comment 'ProfileEvents[S3PutObject]'
    ProfileEvents_S3GetObject Int64, -- comment 'ProfileEvents[S3GetObject]'
    ProfileEvents_ReadBufferFromS3Bytes Int64, -- comment 'ProfileEvents[ReadBufferFromS3Bytes]'
    ProfileEvents_WriteBufferFromS3Bytes Int64, -- comment 'ProfileEvents[WriteBufferFromS3Bytes]'

    -- log_comment contains mixed data quality, we may want to copy something from it, but overall is full of data
    -- log_comment                           String, -- comment 'Log comment. It can be set to arbitrary string no longer than max_query_size. An empty string if it is not defined.',

    -- columns extracted from log_comment, prefixed with lc_
    lc_workflow LowCardinality(String), -- comment 'log_comment[workflow]',
    lc_kind LowCardinality(String), -- comment 'log_comment[kind]',
    lc_id String, -- comment 'log_comment[id]',
    lc_route_id String, -- comment 'log_comment[route_id]',

    lc_access_method LowCardinality(String), -- comment 'log_comment[access_method]',
    lc_api_key_label String,
    lc_api_key_mask String,

    lc_query_type LowCardinality(String), -- comment 'log_comment[query_type]',
    lc_product LowCardinality(String), -- comment 'log_comment[product]',
    lc_chargeable Bool, -- comment 'log_comment[chargeable]',
    lc_name String, -- comment 'log_comment[name]',
    lc_client_query_id String, -- comment 'log_comment[client_query_id]'

    lc_org_id String, -- comment 'log_comment[org_id]',
    lc_team_id Int64, -- comment 'log_comment[team_id]',
    lc_user_id Int64, -- comment 'log_comment[user_id]',
    lc_session_id String, -- comment 'log_comment[session_id]',

    lc_dashboard_id Int64, -- comment 'log_comment[dashboard_id]',
    lc_insight_id Int64, -- comment 'log_comment[insight_id]',
    lc_cohort_id Int64, -- comment 'log_comment[cohort_id]',
    lc_batch_export_id String, -- comment 'log_comment[batch_export_id]'
    lc_experiment_id Int64, -- comment 'log_comment[experiment_id]',
    lc_experiment_feature_flag_key String, -- comment 'log_comment[experiment_feature_flag_key]'

    -- for entries with 'query' tag
    lc_query__kind LowCardinality(String), -- comment 'log_comment[query][kind]', if the query has a source, then source kind is used,
    lc_query__query String, -- comment 'log_comment[query][query]', if query has source, the source query is used instead,

    -- for temporal worflows (ph_kind='temporal')
    lc_temporal__workflow_namespace String, -- comment 'JSONExtractString(log_comment, temporal, workflow_namespace)',
    lc_temporal__workflow_type String, -- comment 'JSONExtractString(log_comment, temporal, workflow_type)',
    lc_temporal__workflow_id String, -- comment 'JSONExtractString(log_comment, temporal, workflow_id)',
    lc_temporal__workflow_run_id String, -- comment 'JSONExtractString(log_comment, temporal, workflow_run_id)',
    lc_temporal__activity_type String, -- comment 'JSONExtractString(log_comment, temporal, activity_type)',
    lc_temporal__activity_id String, -- comment 'JSONExtractString(log_comment, temporal, activity_id)',
    lc_temporal__attempt Int64, -- comment 'JSONExtractString(log_comment, temporal, attempt)'

    -- dagster workflows
    lc_dagster__job_name String,  -- comment JSONExtractString(log_comment, 'dagster', 'job_name')
    lc_dagster__run_id String,  -- comment JSONExtractString(log_comment, 'dagster', 'run_id')
    lc_dagster__owner String,  -- comment JSONExtractString(log_comment, 'dagster', 'tags', 'owner')

    team_id Int64 ALIAS lc_team_id -- alias so that hogql generator can filter by team_id
) ENGINE = {engine}
"""


def QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(table_name="query_log_archive_new"):
    return """
CREATE TABLE IF NOT EXISTS {table_name} (
    hostname                              LowCardinality(String),
    user                                  LowCardinality(String),
    query_id                              String,
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
    exception_name                        String ALIAS errorCodeToName(exception_code),
    exception                             String,
    stack_trace                           String,

    ProfileEvents_RealTimeMicroseconds Int64,
    ProfileEvents_OSCPUVirtualTimeMicroseconds Int64,

    ProfileEvents_S3Clients Int64,
    ProfileEvents_S3DeleteObjects Int64,
    ProfileEvents_S3CopyObject Int64,
    ProfileEvents_S3ListObjects Int64,
    ProfileEvents_S3HeadObject Int64,
    ProfileEvents_S3GetObjectAttributes Int64,
    ProfileEvents_S3CreateMultipartUpload Int64,
    ProfileEvents_S3UploadPartCopy Int64,
    ProfileEvents_S3UploadPart Int64,
    ProfileEvents_S3AbortMultipartUpload Int64,
    ProfileEvents_S3CompleteMultipartUpload Int64,
    ProfileEvents_S3PutObject Int64,
    ProfileEvents_S3GetObject Int64,
    ProfileEvents_ReadBufferFromS3Bytes Int64,
    ProfileEvents_WriteBufferFromS3Bytes Int64,

    lc_workflow LowCardinality(String),
    lc_kind LowCardinality(String),
    lc_id String,
    lc_route_id String,

    lc_access_method LowCardinality(String),
    lc_api_key_label String,
    lc_api_key_mask String,

    lc_query_type LowCardinality(String),
    lc_product LowCardinality(String),
    lc_chargeable Bool,
    lc_name String,
    lc_request_name String,
    lc_client_query_id String,

    lc_org_id String,
    team_id Int64, -- renamed from lc_team_id, no longer an alias
    lc_user_id Int64,
    lc_session_id String,

    lc_dashboard_id Int64,
    lc_insight_id Int64,
    lc_cohort_id Int64,
    lc_batch_export_id String,
    lc_experiment_id Int64,
    lc_experiment_feature_flag_key String,

    lc_alert_config_id String,
    lc_feature LowCardinality(String),
    lc_table_id String,
    lc_warehouse_query Bool,
    lc_person_on_events_mode LowCardinality(String),
    lc_service_name String,
    lc_workload LowCardinality(String),

    lc_query__kind LowCardinality(String),
    lc_query__query String,

    lc_temporal__workflow_namespace String,
    lc_temporal__workflow_type String,
    lc_temporal__workflow_id String,
    lc_temporal__workflow_run_id String,
    lc_temporal__activity_type String,
    lc_temporal__activity_id String,
    lc_temporal__attempt Int64,

    lc_dagster__job_name String,
    lc_dagster__run_id String,
    lc_dagster__owner String
) ENGINE = {engine}
PARTITION BY toYYYYMM(event_date)
ORDER BY (team_id, event_date, event_time, query_id)
PRIMARY KEY (team_id, event_date, event_time, query_id)
    """.format(
        table_name=table_name,
        engine=QUERY_LOG_ARCHIVE_TABLE_ENGINE_NEW(),
    )


MV_SELECT_SQL = """
SELECT
    hostname,
    user,
    query_id,
    type,

    event_date,
    event_time,
    event_time_microseconds,
    query_start_time,
    query_start_time_microseconds,
    query_duration_ms,

    read_rows,
    read_bytes,
    written_rows,
    written_bytes,
    result_rows,
    result_bytes,
    memory_usage,
    peak_threads_usage,

    current_database,
    query,
    formatted_query,
    normalized_query_hash,
    query_kind,

    exception_code,
    exception,
    stack_trace,

    ProfileEvents['RealTimeMicroseconds'] as ProfileEvents_RealTimeMicroseconds,
    ProfileEvents['OSCPUVirtualTimeMicroseconds'] as ProfileEvents_OSCPUVirtualTimeMicroseconds,

    ProfileEvents['S3Clients'] as ProfileEvents_S3Clients,
    ProfileEvents['S3DeleteObjects'] as ProfileEvents_S3DeleteObjects,
    ProfileEvents['S3CopyObject'] as ProfileEvents_S3CopyObject,
    ProfileEvents['S3ListObjects'] as ProfileEvents_S3ListObjects,
    ProfileEvents['S3HeadObject'] as ProfileEvents_S3HeadObject,
    ProfileEvents['S3GetObjectAttributes'] as ProfileEvents_S3GetObjectAttributes,
    ProfileEvents['S3CreateMultipartUpload'] as ProfileEvents_S3CreateMultipartUpload,
    ProfileEvents['S3UploadPartCopy'] as ProfileEvents_S3UploadPartCopy,
    ProfileEvents['S3UploadPart'] as ProfileEvents_S3UploadPart,
    ProfileEvents['S3AbortMultipartUpload'] as ProfileEvents_S3AbortMultipartUpload,
    ProfileEvents['S3CompleteMultipartUpload'] as ProfileEvents_S3CompleteMultipartUpload,
    ProfileEvents['S3PutObject'] as ProfileEvents_S3PutObject,
    ProfileEvents['S3GetObject'] as ProfileEvents_S3GetObject,
    ProfileEvents['ReadBufferFromS3Bytes'] as ProfileEvents_ReadBufferFromS3Bytes,
    ProfileEvents['WriteBufferFromS3Bytes'] as ProfileEvents_WriteBufferFromS3Bytes,

    JSONExtractString(log_comment, 'workflow') as lc_workflow,
    JSONExtractString(log_comment, 'kind') as lc_kind,
    JSONExtractString(log_comment, 'id') as lc_id,
    JSONExtractString(log_comment, 'route_id') as lc_route_id,

    JSONExtractString(log_comment, 'access_method') as lc_access_method,
    JSONExtractString(log_comment, 'api_key_label') as lc_api_key_label,
    JSONExtractString(log_comment, 'api_key_mask') as lc_api_key_mask,

    JSONExtractString(log_comment, 'query_type') as lc_query_type,
    JSONExtractString(log_comment, 'product') as lc_product,
    JSONExtractInt(log_comment, 'chargeable') == 1 as lc_chargeable,
    JSONExtractString(log_comment, 'name') as lc_name,
    JSONExtractString(log_comment, 'request_name') as lc_request_name,
    JSONExtractString(log_comment, 'client_query_id') as lc_client_query_id,

    JSONExtractString(log_comment, 'org_id') as lc_org_id,
    JSONExtractInt(log_comment, 'team_id') as team_id,
    JSONExtractInt(log_comment, 'user_id') as lc_user_id,
    JSONExtractString(log_comment, 'session_id') as lc_session_id,

    JSONExtractInt(log_comment, 'dashboard_id') as lc_dashboard_id,
    JSONExtractInt(log_comment, 'insight_id') as lc_insight_id,
    JSONExtractInt(log_comment, 'cohort_id') as lc_cohort_id,
    JSONExtractString(log_comment, 'batch_export_id') as lc_batch_export_id,
    JSONExtractInt(log_comment, 'experiment_id') as lc_experiment_id,
    JSONExtractString(log_comment, 'experiment_feature_flag_key') as lc_experiment_feature_flag_key,

    JSONExtractString(log_comment, 'alert_config_id') as lc_alert_config_id,
    JSONExtractString(log_comment, 'feature') as lc_feature,
    JSONExtractString(log_comment, 'table_id') as lc_table_id,
    JSONExtractInt(log_comment, 'warehouse_query') == 1 as lc_warehouse_query,
    JSONExtractString(log_comment, 'person_on_events_mode') as lc_person_on_events_mode,
    JSONExtractString(log_comment, 'service_name') as lc_service_name,
    JSONExtractString(log_comment, 'workload') as lc_workload,

    -- for entries with 'query' tag, some queries have source, we should use this
    if(JSONHas(log_comment, 'query', 'source'),
        JSONExtractString(log_comment, 'query', 'source', 'kind'),
        JSONExtractString(log_comment, 'query', 'kind')) as lc_query__kind,
    if(JSONHas(log_comment, 'query', 'source'),
        JSONExtractString(log_comment, 'query', 'source', 'query'),
        JSONExtractString(log_comment, 'query', 'query')) as lc_query__query,

    JSONExtractString(log_comment, 'temporal', 'workflow_namespace') as lc_temporal__workflow_namespace,
    JSONExtractString(log_comment, 'temporal', 'workflow_type') as lc_temporal__workflow_type,
    JSONExtractString(log_comment, 'temporal', 'workflow_id') as lc_temporal__workflow_id,
    JSONExtractString(log_comment, 'temporal', 'workflow_run_id') as lc_temporal__workflow_run_id,
    JSONExtractString(log_comment, 'temporal', 'activity_type') as lc_temporal__activity_type,
    JSONExtractString(log_comment, 'temporal', 'activity_id') as lc_temporal__activity_id,
    JSONExtractInt(log_comment, 'temporal', 'attempt') as lc_temporal__attempt,

    JSONExtractString(log_comment, 'dagster', 'job_name') as lc_dagster__job_name,
    JSONExtractString(log_comment, 'dagster', 'run_id') as lc_dagster__run_id,
    JSONExtractString(log_comment, 'dagster', 'tags', 'owner') as lc_dagster__owner
FROM system.query_log
WHERE
    type != 'QueryStart'
    AND is_initial_query
"""


def QUERY_LOG_ARCHIVE_NEW_MV_SQL(view_name="query_log_archive_new_mv", dest_table="query_log_archive_new"):
    return """CREATE MATERIALIZED VIEW IF NOT EXISTS {view_name}
TO {dest_table}
AS {select_sql}
    """.format(
        view_name=view_name,
        dest_table=dest_table,
        select_sql=MV_SELECT_SQL,
    )


# V4 - adding lc_request_name
ADD_LC_REQUEST_NAME_SQL = """
ALTER TABLE query_log_archive ADD COLUMN IF NOT EXISTS lc_request_name String AFTER lc_name
"""


def QUERY_LOG_ARCHIVE_MV_V4_SQL():
    return """
ALTER TABLE query_log_archive_mv MODIFY QUERY
{select_sql}
    """.format(select_sql=MV_SELECT_SQL)


# V5 - adding exception_name
ADD_EXCEPTION_NAME_SQL = """
ALTER TABLE query_log_archive ADD COLUMN IF NOT EXISTS exception_name String ALIAS errorCodeToName(exception_code) AFTER exception_code
"""
