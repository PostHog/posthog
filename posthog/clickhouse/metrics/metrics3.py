from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplacingMergeTree, ReplicationScheme

from .metrics2 import METRICS2_INPUT_TABLE_NAME

METRIC_SERIES3_TABLE_NAME = "metric_series3"
METRIC_ATTRIBUTES3_TABLE_NAME = "metric_attributes3"
METRIC_NAMES3_TABLE_NAME = "metric_names3"


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def METRIC_SERIES3_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRIC_SERIES3_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(Delta(8), Default),
    `metric_type` LowCardinality(String),
    `unit` LowCardinality(String),
    `aggregation_temporality` LowCardinality(String),
    `is_monotonic` Bool DEFAULT false,
    `service_name` LowCardinality(String),
    `instrumentation_scope` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes),
    `attributes` Map(LowCardinality(String), String),
    `last_seen` DateTime64(6),
    `original_expiry_timestamp` DateTime64(6),
    INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_last_seen_minmax last_seen TYPE minmax GRANULARITY 1
)
ENGINE = {ReplacingMergeTree(METRIC_SERIES3_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED, ver="last_seen")}
PARTITION BY toDate(original_expiry_timestamp)
ORDER BY (team_id, metric_name, series_fingerprint)
TTL original_expiry_timestamp
SETTINGS index_granularity = 8192
"""


def METRIC_ATTRIBUTES3_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRIC_ATTRIBUTES3_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(METRIC_ATTRIBUTES3_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)
TTL original_expiry_time_bucket
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRIC_NAMES3_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRIC_NAMES3_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `original_expiry_timestamp` SimpleAggregateFunction(max, DateTime64(6))
)
ENGINE = {AggregatingMergeTree(METRIC_NAMES3_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, time_bucket, metric_name, original_expiry_time_bucket)
TTL original_expiry_timestamp
SETTINGS index_granularity = 8192
"""


def METRICS2_INPUT_TO_METRIC_NAMES3_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_metric_names3 TO {db}.{METRIC_NAMES3_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `original_expiry_timestamp` SimpleAggregateFunction(max, DateTime64(6))
)
AS SELECT
    team_id,
    metric_name,
    toStartOfHour(timestamp) AS time_bucket,
    toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
    maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
FROM {db}.{METRICS2_INPUT_TABLE_NAME} AS input
WHERE has_labels
GROUP BY team_id, time_bucket, metric_name, original_expiry_time_bucket
"""


def METRICS2_INPUT_TO_METRIC_SERIES3_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_metric_series3 TO {db}.{METRIC_SERIES3_TABLE_NAME}
AS SELECT
    team_id,
    metric_name,
    series_fingerprint,
    metric_type,
    unit,
    aggregation_temporality,
    is_monotonic,
    service_name,
    instrumentation_scope,
    resource_attributes,
    attributes,
    timestamp AS last_seen,
    original_expiry_timestamp
FROM {db}.{METRICS2_INPUT_TABLE_NAME}
WHERE has_labels
"""


def _attributes_mv(view_suffix: str, source_map: str, attribute_type: str, filter_long_pairs: bool) -> str:
    db = _db()
    attributes_expr = (
        f"mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), {source_map})"
        if filter_long_pairs
        else source_map
    )
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{view_suffix} TO {db}.{METRIC_ATTRIBUTES3_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    metric_name,
    time_bucket,
    original_expiry_time_bucket,
    service_name,
    attribute_key,
    attribute_value,
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        metric_name AS metric_name,
        toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
        service_name AS service_name,
        {attributes_expr} AS filtered_attributes,
        arrayJoin(filtered_attributes) AS attribute,
        '{attribute_type}' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {db}.{METRICS2_INPUT_TABLE_NAME}
    WHERE has_labels
    GROUP BY
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        filtered_attributes
)
"""


def METRICS2_INPUT_TO_METRIC_ATTRIBUTES3_MV() -> str:
    return _attributes_mv("metric_attributes3", "attributes", "metric", filter_long_pairs=True)


def METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES3_MV() -> str:
    return _attributes_mv("resource_attributes3", "resource_attributes", "resource", filter_long_pairs=False)
