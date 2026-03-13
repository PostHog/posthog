from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

from .metric_attributes import TABLE_NAME as METRIC_ATTRIBUTES_TABLE_NAME

TABLE_NAME = "metrics31"


def METRICS31_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
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
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `metric_name` LowCardinality(String) CODEC(ZSTD(1)),
    `metric_type` LowCardinality(String) CODEC(ZSTD(1)),
    `value` Float64 CODEC(Gorilla, ZSTD(1)),
    `count` UInt64 DEFAULT 1 CODEC(T64, ZSTD(1)),
    `histogram_bounds` Array(Float64) CODEC(ZSTD(1)),
    `histogram_counts` Array(UInt64) CODEC(ZSTD(1)),
    `unit` LowCardinality(String) CODEC(ZSTD(1)),
    `aggregation_temporality` LowCardinality(String) CODEC(ZSTD(1)),
    `is_monotonic` Bool DEFAULT false CODEC(ZSTD(1)),
    `resource_attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `attributes_map_float` Map(LowCardinality(String), Float64) CODEC(ZSTD(1)),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    INDEX idx_metric_name_set metric_name TYPE set(100) GRANULARITY 1,
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint,
            count() AS event_count,
            sum(value) AS total_value,
            min(value) AS min_value,
            max(value) AS max_value
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint
    )
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
ORDER BY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRICS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.metrics AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=f"{TABLE_NAME}",
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )


def METRIC_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_metric_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{METRIC_ATTRIBUTES_TABLE_NAME}
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
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
        arrayJoin(attributes) AS attribute,
        'metric' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attributes
)
"""


def METRIC_RESOURCE_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_resource_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{METRIC_ATTRIBUTES_TABLE_NAME}
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
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        'resource' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        resource_attributes
)
"""
