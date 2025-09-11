# Note: These tables are not (yet) created automatically, as they're considered experimental on cloud and exact schema is in flux.

from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION, kafka_engine
from posthog.clickhouse.table_engines import MergeTreeEngine
from posthog.kafka_client.topics import KAFKA_METRICS_TIME_TO_SEE_DATA
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

METRICS_TIME_TO_SEE_ENGINE = lambda: MergeTreeEngine("metrics_time_to_see_data", force_unique_zk_path=True)
CREATE_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
    `team_events_last_month` UInt64,
    `query_id` String,
    `primary_interaction_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `timestamp` DateTime64,
    `type` LowCardinality(String),
    `context` LowCardinality(String),
    `is_primary_interaction` UInt8,
    `time_to_see_data_ms` UInt64,
    `status` LowCardinality(String),
    `api_response_bytes` UInt64,
    `current_url` String,
    `api_url` String,
    `insight` LowCardinality(String),
    `action` LowCardinality(String),
    `insights_fetched` UInt16,
    `insights_fetched_cached` UInt16,
    `min_last_refresh` DateTime64,
    `max_last_refresh` DateTime64
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {METRICS_TIME_TO_SEE_ENGINE()}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, user_id)
"""
)

DROP_METRICS_TIME_TO_SEE_TABLE = lambda: f"DROP TABLE metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

CREATE_KAFKA_METRICS_TIME_TO_SEE = (
    lambda: f"""
CREATE TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
    `team_events_last_month` UInt64,
    `query_id` String,
    `team_id` UInt64,
    `user_id` UInt64,
    `session_id` String,
    `timestamp` DateTime64,
    `type` LowCardinality(String),
    `context` LowCardinality(String),
    `primary_interaction_id` String,
    `is_primary_interaction` UInt8,
    `time_to_see_data_ms` UInt64,
    `status` LowCardinality(String),
    `api_response_bytes` UInt64,
    `current_url` String,
    `api_url` String,
    `insight` LowCardinality(String),
    `action` LowCardinality(String),
    `insights_fetched` UInt16,
    `insights_fetched_cached` UInt16,
    `min_last_refresh` DateTime64,
    `max_last_refresh` DateTime64
)
ENGINE={kafka_engine(topic=KAFKA_METRICS_TIME_TO_SEE_DATA)}
SETTINGS kafka_skip_broken_messages = 9999
"""
)
DROP_KAFKA_METRICS_TIME_TO_SEE = (
    lambda: f"DROP TABLE kafka_metrics_time_to_see_data ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"
)

CREATE_METRICS_TIME_TO_SEE_MV = (
    lambda: f"""
CREATE MATERIALIZED VIEW metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'
TO {CLICKHOUSE_DATABASE}.metrics_time_to_see_data
AS SELECT
dictGet('team_events_last_month_dictionary', 'event_count', team_id) AS team_events_last_month,
query_id,
team_id,
user_id,
session_id,
timestamp,
type,
context,
primary_interaction_id,
is_primary_interaction,
time_to_see_data_ms,
status,
api_response_bytes,
current_url,
api_url,
insight,
action,
insights_fetched,
insights_fetched_cached,
min_last_refresh,
max_last_refresh,
_timestamp,
_offset,
_partition
FROM {CLICKHOUSE_DATABASE}.kafka_metrics_time_to_see_data
"""
)
DROP_METRICS_TIME_TO_SEE_MV = lambda: f"DROP TABLE metrics_time_to_see_data_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}' SYNC"

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

# NOTE Tim May 2024: removed this as it was doing a bunch of queries. Should move this to schema migration if we want to keep it.
# :KLUDGE: Temporary tooling to make (re)creating this schema easier
# Invoke via `python manage.py shell <  posthog/models/query_metrics/sql.py`
# if __name__ == "django.core.management.commands.shell":
#     print("To drop query metrics schema:\n")  # noqa: T201
#     for drop_query in reversed(
#         [
#             DROP_TEAM_EVENTS_LAST_MONTH_VIEW,
#             DROP_TEAM_EVENTS_LAST_MONTH_DICTIONARY,
#             DROP_METRICS_TIME_TO_SEE_TABLE,
#             DROP_KAFKA_METRICS_TIME_TO_SEE,
#             DROP_METRICS_TIME_TO_SEE_MV,
#             DROP_METRICS_QUERY_LOG,
#             DROP_METRICS_QUERY_LOG_MV,
#         ]
#     ):
#         print(drop_query())  # noqa: T201
#         print()  # noqa: T201

#     print("To create query metrics schema:\n")  # noqa: T201
#     for create_query in [
#         CREATE_TEAM_EVENTS_LAST_MONTH_VIEW,
#         CREATE_TEAM_EVENTS_LAST_MONTH_DICTIONARY,
#         CREATE_METRICS_TIME_TO_SEE,
#         CREATE_KAFKA_METRICS_TIME_TO_SEE,
#         CREATE_METRICS_TIME_TO_SEE_MV,
#         CREATE_METRICS_QUERY_LOG,
#         CREATE_METRICS_QUERY_LOG_MV,
#     ]:
#         print(create_query())  # noqa: T201
#         print()  # noqa: T201
