from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme


QUERY_LOG_ARCHIVE_DATA_TABLE = "query_log_archive"


def QUERY_LOG_ARCHIVE_TABLE_ENGINE():
    return MergeTreeEngine("query_log_archive", replication_scheme=ReplicationScheme.REPLICATED)


CREATE_QUERY_LOG_ARCHIVE_BASE_TABLE = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
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
    lc_temporal__attempt Int64 -- comment 'JSONExtractString(log_comment, temporal, attempt)'
) ENGINE = {engine}
"""


def QUERY_LOG_ARCHIVE_TABLE_SQL(on_cluster=True):
    return (
        CREATE_QUERY_LOG_ARCHIVE_BASE_TABLE
        + """
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, event_time)
    """
    ).format(
        table_name=QUERY_LOG_ARCHIVE_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=QUERY_LOG_ARCHIVE_TABLE_ENGINE(),
    )


def QUERY_LOG_ARCHIVE_MV(on_cluster=True):
    return """CREATE MATERIALIZED VIEW query_log_archive_mv {on_cluster_clause}
TO {table_name}
AS SELECT
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

    JSONExtractString(log_comment, 'query_type') as lc_query_type,
    JSONExtractString(log_comment, 'product') as lc_product,
    JSONExtractInt(log_comment, 'chargeable') == 1 as lc_chargeable,
    JSONExtractString(log_comment, 'name') as lc_name,
    JSONExtractString(log_comment, 'client_query_id') as lc_client_query_id,

    JSONExtractString(log_comment, 'org_id') as lc_org_id,
    JSONExtractInt(log_comment, 'team_id') as lc_team_id,
    JSONExtractInt(log_comment, 'user_id') as lc_user_id,
    JSONExtractString(log_comment, 'session_id') as lc_session_id,

    JSONExtractInt(log_comment, 'dashboard_id') as lc_dashboard_id,
    JSONExtractInt(log_comment, 'insight_id') as lc_insight_id,
    JSONExtractInt(log_comment, 'cohort_id') as lc_cohort_id,
    JSONExtractString(log_comment, 'batch_export_id') as lc_batch_export_id,
    JSONExtractInt(log_comment, 'experiment_id') as lc_experiment_id,
    JSONExtractString(log_comment, 'experiment_feature_flag_key') as lc_experiment_feature_flag_key,

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
    JSONExtractInt(log_comment, 'temporal', 'attempt') as lc_temporal__attempt
FROM system.query_log
WHERE
    type != 'QueryStart'
    AND is_initial_query
    """.format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        table_name=QUERY_LOG_ARCHIVE_DATA_TABLE,
    )
