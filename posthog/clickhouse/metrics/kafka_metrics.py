"""Kafka ingest for the metrics product: `clickhouse_metrics` topic -> `kafka_metrics_avro`
-> materialized views into `metrics1` (raw), `metric_samples1` + `metric_series1` (the split
the samples/exemplar queries read), and `metrics_kafka_metrics` (consumer-lag bookkeeping).

These objects are modeled in the all-env HCL layer
(`posthog/clickhouse/hcl/roles/logs/metrics`); this module is the migration-applied
equivalent so local and multinode dev get a working ingest chain too, the same way
`posthog/clickhouse/traces/spans.py` does for trace spans. Keep the SQL in sync with the
HCL definitions — the multinode convergence gate diffs the live schema against the goldens.
"""

from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplicationScheme

from .metric_events import SAMPLES_TABLE_NAME, SERIES_TABLE_NAME
from .metrics1 import TABLE_NAME as METRICS1_TABLE_NAME

KAFKA_TABLE_NAME = "kafka_metrics_avro"
KAFKA_METRICS_TABLE_NAME = "metrics_kafka_metrics"
KAFKA_NAMED_COLLECTION = "warpstream_metrics"
KAFKA_TOPIC = "clickhouse_metrics"
KAFKA_GROUP = "clickhouse-metrics-avro-new"


def KAFKA_METRICS_AVRO_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{KAFKA_TABLE_NAME}
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
    `series_fingerprint` Nullable(Int64)
)
ENGINE = {kafka_engine(topic=KAFKA_TOPIC, group=KAFKA_GROUP, serialization="Avro", named_collection=KAFKA_NAMED_COLLECTION)}
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 8,
    kafka_poll_timeout_ms = 3000,
    kafka_poll_max_batch_size = 1000
"""


def KAFKA_METRICS_AVRO_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_mv TO {db}.{METRICS1_TABLE_NAME}
AS SELECT
    uuid,
    trace_id,
    span_id,
    ifNull(trace_flags, 0) AS trace_flags,
    timestamp,
    observed_timestamp,
    ifNull(service_name, '') AS service_name,
    ifNull(metric_name, '') AS metric_name,
    ifNull(metric_type, '') AS metric_type,
    ifNull(value, 0) AS value,
    toUInt64(ifNull(count, 1)) AS count,
    histogram_bounds,
    arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
    ifNull(unit, '') AS unit,
    ifNull(aggregation_temporality, '') AS aggregation_temporality,
    ifNull(is_monotonic, 0) AS is_monotonic,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    ifNull(instrumentation_scope, '') AS instrumentation_scope,
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapFilter((k, v) -> isNotNull(v), mapApply((k, v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))), attributes))) AS attributes_map_float,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id
FROM {db}.{KAFKA_TABLE_NAME}
SETTINGS
    min_insert_block_size_rows = 0,
    min_insert_block_size_bytes = 0
"""


def KAFKA_METRICS_AVRO_TO_METRIC_SAMPLES_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_to_metric_samples TO {db}.{SAMPLES_TABLE_NAME}
AS SELECT
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    ifNull(metric_name, '') AS metric_name,
    reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
    timestamp,
    ifNull(value, 0) AS value,
    toUInt64(ifNull(count, 1)) AS count,
    histogram_bounds,
    arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
    trace_id,
    span_id,
    ifNull(trace_flags, 0) AS trace_flags
FROM {db}.{KAFKA_TABLE_NAME}
WHERE {KAFKA_TABLE_NAME}.series_fingerprint IS NOT NULL
SETTINGS
    min_insert_block_size_rows = 0,
    min_insert_block_size_bytes = 0
"""


def KAFKA_METRICS_AVRO_TO_METRIC_SERIES_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_to_metric_series TO {db}.{SERIES_TABLE_NAME}
AS SELECT
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    ifNull(metric_name, '') AS metric_name,
    reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
    ifNull(metric_type, '') AS metric_type,
    ifNull(unit, '') AS unit,
    ifNull(aggregation_temporality, '') AS aggregation_temporality,
    ifNull(is_monotonic, 0) AS is_monotonic,
    ifNull(service_name, '') AS service_name,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)) AS attributes,
    timestamp AS last_seen
FROM {db}.{KAFKA_TABLE_NAME}
WHERE {KAFKA_TABLE_NAME}.series_fingerprint IS NOT NULL
SETTINGS
    min_insert_block_size_rows = 0,
    min_insert_block_size_bytes = 0
"""


def METRICS_KAFKA_METRICS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{KAFKA_METRICS_TABLE_NAME}
(
    `_partition` UInt32,
    `_topic` String,
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_created_at` SimpleAggregateFunction(max, DateTime64(9)),
    `max_lag` SimpleAggregateFunction(max, UInt64)
)
ENGINE = {AggregatingMergeTree(KAFKA_METRICS_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
ORDER BY (_topic, _partition)
SETTINGS
    index_granularity = 8192
"""


def KAFKA_METRICS_AVRO_TO_KAFKA_METRICS_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_kafka_metrics_mv TO {db}.{KAFKA_METRICS_TABLE_NAME}
AS SELECT
    _partition,
    _topic,
    maxSimpleState(_offset) AS max_offset,
    maxSimpleState(observed_timestamp) AS max_observed_timestamp,
    maxSimpleState(timestamp) AS max_timestamp,
    maxSimpleState(now()) AS max_created_at,
    maxSimpleState(now() - observed_timestamp) AS max_lag
FROM {db}.{KAFKA_TABLE_NAME}
GROUP BY _partition, _topic
"""
