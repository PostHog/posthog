"""
ClickHouse schema definitions for logs cluster.

This module defines table schemas for the logs cluster used in tests.
These definitions mirror the SQL in bin/clickhouse-logs.sql but are used
to create tables directly in the test environment without running migrations.
"""

from posthog.settings import CLICKHOUSE_CLUSTER

# UDF for extracting IPv4 addresses
CREATE_UDF_EXTRACT_IPV4_SUBSTRINGS = """
CREATE OR REPLACE FUNCTION extractIPv4Substrings AS
(
  body -> extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\\.){2,2}([0-9]))')
)
"""

# Main logs table (logs31)
LOGS_DATA_TABLE = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS logs31
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `trace_flags` Int32 CODEC(ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `observed_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
    `body` String CODEC(ZSTD(1)),
    `severity_text` String CODEC(ZSTD(1)),
    `severity_number` Int32 CODEC(ZSTD(1)),
    `service_name` String CODEC(ZSTD(1)),
    `resource_attributes` Map(String, String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `resource_id` String CODEC(ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `event_name` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `attributes_map_float` Map(LowCardinality(String), Float64) CODEC(ZSTD(1)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) CODEC(ZSTD(1)),
    `level` String ALIAS severity_text,
    `mat_body_ipv4_matches` Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1{{0,1}}[0-9]){{0,1}}[0-9])\\.){2, 2}([0-9]))'),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram3 body TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint
    )
)
ENGINE = MergeTree
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""
)

# Distributed table for logs
LOGS_DISTRIBUTED_TABLE = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS logs
ENGINE = Distributed('{CLICKHOUSE_CLUSTER}', currentDatabase(), 'logs31')
AS logs31
"""
)

# Log attributes aggregation table
LOG_ATTRIBUTES_TABLE = (
    lambda: f"""
CREATE TABLE IF NOT EXISTS log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_id` String DEFAULT '',
    `resource_fingerprint` UInt64 DEFAULT 0,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = AggregatingMergeTree
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)
"""
)

# Materialized view for resource attributes
LOG_TO_RESOURCE_ATTRIBUTES_MV = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS log_to_resource_attributes TO log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    'resource' as attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM logs31
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
)
"""
)

# Materialized view for log attributes
LOG_TO_LOG_ATTRIBUTES_MV = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS log_to_log_attributes TO log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    'log' as attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM logs31
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
)
"""
)

# Kafka metrics table for monitoring
LOGS_KAFKA_METRICS_TABLE = (
    lambda: """
CREATE TABLE IF NOT EXISTS logs_kafka_metrics
(
    `_partition` UInt32,
    `_topic` String,
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_created_at` SimpleAggregateFunction(max, DateTime64(9)),
    `max_lag` SimpleAggregateFunction(max, UInt64)
)
ENGINE = MergeTree
ORDER BY (_topic, _partition)
"""
)

# Truncate statements for test cleanup
TRUNCATE_LOGS31_TABLE_SQL = "TRUNCATE TABLE IF EXISTS logs31"
TRUNCATE_LOG_ATTRIBUTES_TABLE_SQL = "TRUNCATE TABLE IF EXISTS log_attributes"
TRUNCATE_LOGS_KAFKA_METRICS_TABLE_SQL = "TRUNCATE TABLE IF EXISTS logs_kafka_metrics"


# Query lists for test setup (matching pattern in schema.py)
def build_query(query_fn):
    """Build a query from a callable or return the string directly."""
    return query_fn() if callable(query_fn) else query_fn


# UDF queries (must run first)
CREATE_UDF_QUERIES = [
    CREATE_UDF_EXTRACT_IPV4_SUBSTRINGS,
]

# Data table queries (MergeTree and AggregatingMergeTree tables)
CREATE_DATA_TABLE_QUERIES = [
    LOGS_DATA_TABLE,
    LOG_ATTRIBUTES_TABLE,
    LOGS_KAFKA_METRICS_TABLE,
]

# Distributed table queries
CREATE_DISTRIBUTED_TABLE_QUERIES = [
    LOGS_DISTRIBUTED_TABLE,
]

# Materialized view queries
CREATE_MV_TABLE_QUERIES = [
    LOG_TO_RESOURCE_ATTRIBUTES_MV,
    LOG_TO_LOG_ATTRIBUTES_MV,
]

# All truncate statements for cleanup
TRUNCATE_TABLE_QUERIES = [
    TRUNCATE_LOGS31_TABLE_SQL,
    TRUNCATE_LOG_ATTRIBUTES_TABLE_SQL,
    TRUNCATE_LOGS_KAFKA_METRICS_TABLE_SQL,
]
