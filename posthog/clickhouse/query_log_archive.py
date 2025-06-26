from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme, Distributed

QUERY_LOG_ARCHIVE_DATA_TABLE = "sharded_query_log_archive"

DISTRIBUTED_QUERY_LOG_ARCHIVE_DATA_TABLE = "query_log_archive"


def QUERY_LOG_ARCHIVE_TABLE_ENGINE():
    return MergeTreeEngine("query_log_archive", replication_scheme=ReplicationScheme.SHARDED)


def DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_ENGINE():
    return Distributed(
        data_table=QUERY_LOG_ARCHIVE_DATA_TABLE,
        # sharding_key="rand()",
    )


CREATE_QUERY_LOG_ARCHIVE_BASE_TABLE = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    hostname                              LowCardinality(String), -- comment 'Hostname of the server executing the query.',
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
    current_database                      LowCardinality(String), -- comment 'Name of the current database.',
    query                                 String, -- comment ' Query string.',
    formatted_query                       String, -- comment 'Formatted query string.',
    normalized_query_hash                 UInt64, -- comment 'A numeric hash value, such as it is identical for queries differ only by values of literals.',
    query_kind                            LowCardinality(String), -- comment 'Type of the query.',
    exception_code                        Int32, -- comment 'Code of an exception.',
    exception                             String, -- comment 'Exception message.',
    stack_trace                           String, -- comment 'Stack trace. An empty string, if the query was completed successfully.',
    user                                  LowCardinality(String), -- comment 'Name of the user who initiated the current query.',
    query_id                              String, -- comment 'ID of the query.',
    peak_threads_usage                    UInt64, -- comment 'Maximum count of simultaneous threads executing the query.',
    -- log_comment is a garbage, we may want to copy something from it, but overall is full of data
    -- log_comment                           String, -- comment 'Log comment. It can be set to arbitrary string no longer than max_query_size. An empty string if it is not defined.',

    -- the above columns are copied directly from system.query_log
    ProfileEvents_RealTimeMicroseconds Float64, -- comment 'ProfileEvents[RealTimeMicroseconds]',
    ProfileEvents_OSCPUVirtualTimeMicroseconds Float64, -- comment 'ProfileEvents[OSCPUVirtualTimeMicroseconds]',

    -- columns extracted from log_comment, prefixed with lc_
    lc_kind String, -- comment 'log_comment[kind]',
    lc_id String, -- comment 'log_comment[id]',
    lc_query_type String, -- comment 'log_comment[query_type]',
    lc_product String, -- comment 'log_comment[product]',

    lc_team_id Int64, -- comment 'log_comment[team_id]',
    lc_user_id Int64, -- comment 'log_comment[user_id]',
    lc_org_id String, -- comment 'log_comment[org_id]',
    lc_workflow LowCardinality(String), -- comment 'log_comment[workflow]',
    lc_dashboard_id Int64, -- comment 'log_comment[dashboard_id]',
    lc_insight_id Int64, -- comment 'log_comment[insight_id]',
    lc_name String, -- comment 'log_comment[name]',

    -- for entries with 'query' tag
    lc_query__kind String, -- comment 'log_comment[query][kind]',
    lc_query__query String, -- comment 'log_comment[query][query]', -- comment 'HogQL query',

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


def DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_SQL(on_cluster=True):
    return CREATE_QUERY_LOG_ARCHIVE_BASE_TABLE.format(
        table_name=DISTRIBUTED_QUERY_LOG_ARCHIVE_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=DISTRIBUTED_QUERY_LOG_ARCHIVE_TABLE_ENGINE(),
    )


def QUERY_LOG_ARCHIVE_MV(on_cluster=True):
    return """CREATE MATERIALIZED VIEW query_log_archive_mv {on_cluster_clause}
TO {table_name}
AS SELECT
    hostname,
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
    current_database,
    query,
    formatted_query,
    normalized_query_hash,
    query_kind,
    exception_code,
    exception,
    stack_trace,
    user,
    query_id,
    peak_threads_usage,
    ProfileEvents['RealTimeMicroseconds'] as ProfileEvents_RealTimeMicroseconds,
    ProfileEvents['OSCPUVirtualTimeMicroseconds'] as ProfileEvents_OSCPUVirtualTimeMicroseconds,
    JSONExtractString(log_comment, 'kind') as lc_kind,
    JSONExtractString(log_comment, 'id') as lc_id,
    JSONExtractString(log_comment, 'query_type') as lc_query_type,
    JSONExtractString(log_comment, 'product') as lc_product,
    JSONExtractInt(log_comment, 'team_id') as lc_team_id,
    JSONExtractInt(log_comment, 'user_id') as lc_user_id,
    JSONExtractString(log_comment, 'org_id') as lc_org_id,
    JSONExtractString(log_comment, 'workflow') as lc_workflow,
    JSONExtractInt(log_comment, 'dashboard_id') as lc_dashboard_id,
    JSONExtractInt(log_comment, 'insight_id') as lc_insight_id,
    JSONExtractString(log_comment, 'name') as lc_name,
    JSONExtractString(log_comment, 'query', 'kind') as lc_query__kind,
    JSONExtractString(log_comment, 'query', 'query') as lc_query__query,
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
