# Note: These tables are not (yet) created automatically, as they're considered experimental on cloud and exact schema is in flux.

from posthog.clickhouse.table_engines import MergeTreeEngine
from posthog.settings import CLICKHOUSE_CLUSTER

METRICS_QUERY_LOG_TABLE_ENGINE = lambda: MergeTreeEngine("metrics_query_log", force_unique_zk_path=True)

CREATE_METRICS_QUERY_LOG = (
    lambda: f"""
CREATE TABLE metrics_query_log ON CLUSTER '{CLICKHOUSE_CLUSTER}'
(
    `host` String,
    `timestamp` DateTime,
    `query_duration_ms` UInt64,
    `read_rows` UInt64,
    `read_bytes` UInt64,
    `result_rows` UInt64,
    `result_bytes` UInt64,
    `memory_usage` UInt64,
    `is_initial_query` UInt8,
    `exception_code` Int32,
    `team_id` Int64,
    `team_events_last_month` UInt64,
    `user_id` Int64,
    `session_id` String,
    `kind` String,
    `query_type` String,
    `client_query_id` String,
    `id` String,
    `route_id` String,
    `query_time_range_days` Int64,
    `has_joins` UInt8,
    `has_json_operations` UInt8,
    `filter_by_type` Array(String),
    `breakdown_by` Array(String),
    `entity_math` Array(String),
    `filter` String,
    `ProfileEvents` Map(String, UInt64),
    `tables` Array(LowCardinality(String)),
    `columns` Array(LowCardinality(String)),
    `query` String,
    `log_comment` String
)
ENGINE = {METRICS_QUERY_LOG_TABLE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (toDate(timestamp), team_id, query_type)
SETTINGS index_granularity = 8192
"""
)

CREATE_METRICS_QUERY_LOG_MV = (
    lambda: f"""
CREATE MATERIALIZED VIEW metrics_query_log_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
TO metrics_query_log
AS
SELECT
    getMacro('replica') AS host,
    event_time AS timestamp,
    query_duration_ms,
    read_rows,
    read_bytes,
    result_rows,
    result_bytes,
    memory_usage,
    is_initial_query,
    exception_code > 0 AS is_exception,
    exception_code,
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    dictGet('team_events_last_month_dictionary', 'event_count', team_id) AS team_events_last_month,
    JSONExtractInt(log_comment, 'user_id') AS user_id,
    JSONExtractString(log_comment, 'session_id') AS session_id,
    JSONExtractString(log_comment, 'kind') AS kind,
    JSONExtractString(log_comment, 'query_type') AS query_type,
    JSONExtractString(log_comment, 'client_query_id') AS client_query_id,
    JSONExtractString(log_comment, 'id') AS id,
    JSONExtractString(log_comment, 'route_id') AS route_id,
    JSONExtractInt(log_comment, 'query_time_range_days') AS query_time_range_days,
    JSONExtractBool(log_comment, 'has_joins') AS has_joins,
    JSONExtractBool(log_comment, 'has_json_operations') AS has_json_operations,
    JSONExtract(log_comment, 'filter_by_type', 'Array(String)') as filter_by_type,
    JSONExtract(log_comment, 'breakdown_by', 'Array(String)') as breakdown_by,
    JSONExtract(log_comment, 'entity_math', 'Array(String)') as entity_math,
    JSONExtractString(log_comment, 'filter') AS filter,
    ProfileEvents,
    tables,
    columns,
    query,
    log_comment
FROM system.query_log
WHERE JSONHas(log_comment, 'team_id')
  AND JSONHas(log_comment, 'query_type')
  AND type != 'QueryStart'
"""
)

DROP_METRICS_QUERY_LOG = lambda: f"DROP TABLE metrics_query_log ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"
DROP_METRICS_QUERY_LOG_MV = lambda: f"DROP TABLE metrics_query_log_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"
