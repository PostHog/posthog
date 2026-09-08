from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import (
    AggregatingMergeTree,
    Distributed,
    MergeTreeEngine,
    ReplacingMergeTree,
    ReplicationScheme,
)

from .kafka_metrics import KAFKA_NAMED_COLLECTION, KAFKA_TOPIC

KAFKA_TABLE_NAME = "kafka_metrics_avro2"
KAFKA_GROUP = "clickhouse-metrics-avro2"

METRICS2_INPUT_TABLE_NAME = "metrics2_input"
METRICS2_TABLE_NAME = "metrics2"
METRICS_DISTRIBUTED_TABLE_NAME = "metrics_distributed"
METRIC_SERIES2_TABLE_NAME = "metric_series2"
METRIC_SERIES_DISTRIBUTED_TABLE_NAME = "metric_series_distributed"
METRIC_ATTRIBUTES2_TABLE_NAME = "metric_attributes2"
METRIC_ATTRIBUTES_DISTRIBUTED_TABLE_NAME = "metric_attributes_distributed"

DEFAULT_RETENTION_DAYS = 90


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def KAFKA_METRICS_AVRO2_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{KAFKA_TABLE_NAME}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Nullable(Int32),
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `service_name` Nullable(String),
    `metric_name` Nullable(String),
    `metric_type` Nullable(String),
    `value` Nullable(Float64),
    `count` Nullable(Int64),
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(Int64),
    `unit` Nullable(String),
    `aggregation_temporality` Nullable(String),
    `is_monotonic` Nullable(UInt8),
    `resource_attributes` Map(String, String),
    `instrumentation_scope` Nullable(String),
    `attributes` Map(String, String),
    `series_fingerprint` Nullable(Int64),
    `has_labels` Nullable(UInt8),
    `retention_days` Nullable(Int32)
)
ENGINE = {kafka_engine(topic=KAFKA_TOPIC, group=KAFKA_GROUP, serialization="Avro", named_collection=KAFKA_NAMED_COLLECTION)}
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 8,
    kafka_poll_timeout_ms = 3000,
    kafka_poll_max_batch_size = 1000,
    input_format_avro_allow_missing_fields = 1
"""


def METRICS2_INPUT_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS2_INPUT_TABLE_NAME}
(
    `uuid` String,
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64,
    `resource_fingerprint` UInt64,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `original_expiry_timestamp` DateTime64(6),
    `service_name` LowCardinality(String),
    `metric_type` LowCardinality(String),
    `value` Float64,
    `count` UInt64,
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(UInt64),
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `has_labels` Bool,
    `unit` LowCardinality(String),
    `aggregation_temporality` LowCardinality(String),
    `is_monotonic` Bool,
    `instrumentation_scope` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `attributes` Map(LowCardinality(String), String),
    `_partition` UInt32,
    `_topic` String,
    `_offset` UInt64
)
ENGINE = Null
"""


def METRICS2_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS2_TABLE_NAME}
(
    `uuid` String,
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime MATERIALIZED toStartOfHour(timestamp),
    `series_fingerprint` UInt64 CODEC(Delta, Default),
    `resource_fingerprint` UInt64 DEFAULT 0,
    `timestamp` DateTime64(6) CODEC(DoubleDelta),
    `observed_timestamp` DateTime64(6),
    `original_expiry_timestamp` DateTime64(6),
    `created_at` DateTime64(6) MATERIALIZED now(),
    `service_name` LowCardinality(String),
    `metric_type` LowCardinality(String),
    `value` Float64 CODEC(Gorilla),
    `count` UInt64 DEFAULT 1 CODEC(T64),
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(UInt64),
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `has_labels` Bool DEFAULT false,
    `unit` LowCardinality(String),
    `aggregation_temporality` LowCardinality(String),
    `is_monotonic` Bool DEFAULT false,
    `instrumentation_scope` String,
    `_partition` UInt32,
    `_topic` String,
    `_offset` UInt64,
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_series_minute
    (
        SELECT
            team_id,
            metric_name,
            service_name,
            metric_type,
            resource_fingerprint,
            series_fingerprint,
            toStartOfMinute(timestamp) AS minute,
            count() AS sample_count,
            sum(value) AS total_value,
            min(value) AS min_value,
            max(value) AS max_value,
            argMin(value, timestamp) AS first_value,
            argMax(value, timestamp) AS last_value
        GROUP BY
            team_id,
            metric_name,
            service_name,
            metric_type,
            resource_fingerprint,
            series_fingerprint,
            minute
    ),
    PROJECTION projection_series_activity
    (
        SELECT
            team_id,
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint,
            series_fingerprint,
            toStartOfHour(timestamp) AS hour,
            count() AS sample_count,
            max(timestamp) AS last_seen
        GROUP BY
            team_id,
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint,
            series_fingerprint,
            hour
    )
)
ENGINE = {MergeTreeEngine(METRICS2_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_timestamp)
ORDER BY (team_id, metric_name, time_bucket, series_fingerprint, timestamp)
TTL original_expiry_timestamp
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRIC_SERIES2_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRIC_SERIES2_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(Delta, Default),
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
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {ReplacingMergeTree(METRIC_SERIES2_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED, ver="last_seen")}
ORDER BY (team_id, metric_name, series_fingerprint)
TTL original_expiry_timestamp
SETTINGS index_granularity = 8192
"""


def METRIC_ATTRIBUTES2_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRIC_ATTRIBUTES2_TABLE_NAME}
(
    `team_id` Int32,
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
ENGINE = {AggregatingMergeTree(METRIC_ATTRIBUTES2_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, attribute_key, attribute_value)
TTL original_expiry_time_bucket
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def _distributed_sql(distributed_name: str, data_table: str) -> str:
    return "CREATE TABLE IF NOT EXISTS {database}.{distributed} AS {database}.{table_name} ENGINE = {engine}".format(
        distributed=distributed_name,
        table_name=data_table,
        engine=Distributed(data_table=data_table, cluster=settings.CLICKHOUSE_LOGS_CLUSTER),
        database=_db(),
    )


def METRICS2_DISTRIBUTED_TABLE_SQL() -> str:
    return _distributed_sql(METRICS_DISTRIBUTED_TABLE_NAME, METRICS2_TABLE_NAME)


def METRIC_SERIES2_DISTRIBUTED_TABLE_SQL() -> str:
    return _distributed_sql(METRIC_SERIES_DISTRIBUTED_TABLE_NAME, METRIC_SERIES2_TABLE_NAME)


def METRIC_ATTRIBUTES2_DISTRIBUTED_TABLE_SQL() -> str:
    return _distributed_sql(METRIC_ATTRIBUTES_DISTRIBUTED_TABLE_NAME, METRIC_ATTRIBUTES2_TABLE_NAME)


def KAFKA_METRICS_AVRO2_MV() -> str:
    db = _db()
    sorted_resource_attributes = "mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))"
    sorted_attributes = "mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes))"
    labelled = "toBool(ifNull(has_labels, 1))"
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_mv TO {db}.{METRICS2_INPUT_TABLE_NAME}
AS SELECT
    uuid,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    ifNull(metric_name, '') AS metric_name,
    reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
    cityHash64({sorted_resource_attributes}) AS resource_fingerprint,
    timestamp,
    observed_timestamp,
    observed_timestamp + toIntervalDay(assumeNotNull(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32({DEFAULT_RETENTION_DAYS}))))) AS original_expiry_timestamp,
    ifNull(service_name, '') AS service_name,
    ifNull(metric_type, '') AS metric_type,
    ifNull(value, 0) AS value,
    toUInt64(ifNull(count, 1)) AS count,
    histogram_bounds,
    arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
    trace_id,
    span_id,
    ifNull(trace_flags, 0) AS trace_flags,
    {labelled} AS has_labels,
    ifNull(unit, '') AS unit,
    ifNull(aggregation_temporality, '') AS aggregation_temporality,
    ifNull(is_monotonic, 0) AS is_monotonic,
    ifNull(instrumentation_scope, '') AS instrumentation_scope,
    if({labelled}, {sorted_resource_attributes}, CAST(map(), 'Map(String, String)')) AS resource_attributes,
    if({labelled}, {sorted_attributes}, CAST(map(), 'Map(String, String)')) AS attributes,
    _partition,
    _topic,
    _offset
FROM {db}.{KAFKA_TABLE_NAME}
WHERE {KAFKA_TABLE_NAME}.series_fingerprint IS NOT NULL
SETTINGS
    min_insert_block_size_rows = 0,
    min_insert_block_size_bytes = 0
"""


def METRICS2_INPUT_TO_METRICS_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_metrics TO {db}.{METRICS2_TABLE_NAME}
AS SELECT
    uuid,
    team_id,
    metric_name,
    series_fingerprint,
    resource_fingerprint,
    timestamp,
    observed_timestamp,
    original_expiry_timestamp,
    service_name,
    metric_type,
    value,
    count,
    histogram_bounds,
    histogram_counts,
    trace_id,
    span_id,
    trace_flags,
    has_labels,
    unit,
    aggregation_temporality,
    is_monotonic,
    instrumentation_scope,
    _partition,
    _topic,
    _offset
FROM {db}.{METRICS2_INPUT_TABLE_NAME}
"""


def METRICS2_INPUT_TO_METRIC_SERIES_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_metric_series TO {db}.{METRIC_SERIES2_TABLE_NAME}
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
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{view_suffix} TO {db}.{METRIC_ATTRIBUTES2_TABLE_NAME}
(
    `team_id` Int32,
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
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        filtered_attributes
)
"""


def METRICS2_INPUT_TO_METRIC_ATTRIBUTES_MV() -> str:
    return _attributes_mv("metric_attributes", "attributes", "metric", filter_long_pairs=True)


def METRICS2_INPUT_TO_RESOURCE_ATTRIBUTES_MV() -> str:
    return _attributes_mv("resource_attributes", "resource_attributes", "resource", filter_long_pairs=False)
