"""The metrics4 tables: one row per series and hour, fed from `metrics2_input`.

- `metrics4_samples` holds the data points of one series-hour as parallel arrays
  (`timestamp_arr`, `value_arr`, ...). Readers build one sorted `(ts, value)`
  array per series with `groupArrayArray` over the hour rows, which is the shape
  the PromQL bridge already computes from `metrics2` with `groupArray`.
- `metrics4_series` keeps one label row per series-hour, so it records when a
  series was active.
- `metrics4_names` and `metrics4_attributes` are the hourly name and attribute
  rollups behind the pickers.

Retention counts from the sample timestamp with a 30-day default. The Kafka view
passes the retention a producer asked for through `retention_days_explicit`
(0 when none), so an explicit retention still applies here while `metrics2`
keeps its own 90-day default.

Why the parallel arrays of `metrics4_samples` stay aligned: inside one insert
block every `groupArray(col)` of one key sees the same rows in the same order,
so index `i` of every array is the same source point. On merge the engine applies
`groupArrayArray` (concatenation) to every array column of the equal-key rows in
the same sequence. Nothing sorts the arrays by time, so readers must not assume
time order. `ARRAY JOIN` over several arrays throws when lengths differ, so a
misalignment fails loudly.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplacingMergeTree, ReplicationScheme

from .metrics2 import METRICS2_INPUT_TABLE_NAME

METRICS4_SAMPLES_TABLE_NAME = "metrics4_samples"
METRICS4_SERIES_TABLE_NAME = "metrics4_series"
METRICS4_NAMES_TABLE_NAME = "metrics4_names"
METRICS4_ATTRIBUTES_TABLE_NAME = "metrics4_attributes"

METRICS4_DEFAULT_RETENTION_DAYS = 30

# The expiry of one `metrics2_input` row for the metrics4 tables.
METRICS4_EXPIRY_EXPR = (
    "timestamp + toIntervalDay(if(retention_days_explicit > 0, retention_days_explicit, "
    f"toInt32({METRICS4_DEFAULT_RETENTION_DAYS})))"
)

# (metrics2 column, element type) for every per-point column that becomes an array.
METRICS4_POINT_ARRAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("timestamp", "DateTime64(6)"),
    ("observed_timestamp", "DateTime64(6)"),
    ("value", "Float64"),
    ("count", "UInt64"),
    ("histogram_counts", "Array(UInt64)"),
    ("trace_id", "String"),
    ("span_id", "String"),
    ("trace_flags", "Int32"),
    ("_partition", "UInt32"),
    ("_offset", "UInt64"),
)

# Codecs apply to the element stream of an array. The timestamps and Kafka offsets of one
# row are in insert order, so the delta codecs fit; T64 and Gorilla do not depend on order.
_ARRAY_CODECS: dict[str, str] = {
    "timestamp": " CODEC(DoubleDelta, Default)",
    "observed_timestamp": " CODEC(DoubleDelta, Default)",
    "value": " CODEC(Gorilla, Default)",
    "count": " CODEC(T64, Default)",
    "histogram_counts": " CODEC(T64, Default)",
    "_offset": " CODEC(Delta, Default)",
}


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def METRICS4_SAMPLES_TABLE_SQL() -> str:
    arrays = ",\n".join(
        f"    `{name}_arr` SimpleAggregateFunction(groupArrayArray, Array({element_type})){_ARRAY_CODECS.get(name, '')}"
        for name, element_type in METRICS4_POINT_ARRAY_COLUMNS
    )
    # One row holds a full hour of one series, so a granule of 8192 rows would span every
    # series of an insert and the key filter could not skip any of it. A granule that spans
    # several metric names has a key range that contains every `time_bucket` of the smaller
    # names, so the primary key alone cannot prune by hour; the minmax index on `time_bucket`
    # does, as `idx_timestamp_minmax` does for `metrics2`.
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS4_SAMPLES_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime,
    `series_fingerprint` UInt64 CODEC(Delta(8), Default),
    `original_expiry_date` Date32,
    `resource_fingerprint` SimpleAggregateFunction(any, UInt64),
    `service_name` SimpleAggregateFunction(any, LowCardinality(String)),
    `metric_type` SimpleAggregateFunction(any, LowCardinality(String)),
    `unit` SimpleAggregateFunction(any, LowCardinality(String)),
    `aggregation_temporality` SimpleAggregateFunction(any, LowCardinality(String)),
    `is_monotonic` SimpleAggregateFunction(max, UInt8),
    `has_labels` SimpleAggregateFunction(max, UInt8),
    `instrumentation_scope` SimpleAggregateFunction(any, String),
    `histogram_bounds` SimpleAggregateFunction(anyLast, Array(Float64)),
    `_topic` SimpleAggregateFunction(any, LowCardinality(String)),
{arrays},
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_time_bucket_minmax time_bucket TYPE minmax GRANULARITY 1,
    INDEX idx_trace_id_bf trace_id_arr TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(METRICS4_SAMPLES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY original_expiry_date
ORDER BY (team_id, metric_name, time_bucket, series_fingerprint)
TTL original_expiry_date
SETTINGS
    index_granularity = 128,
    ttl_only_drop_parts = 1
"""


def METRICS4_SERIES_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS4_SERIES_TABLE_NAME}
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
    `timestamp` DateTime64(6),
    `time_bucket` DateTime MATERIALIZED toStartOfHour(timestamp),
    `original_expiry_timestamp` DateTime64(6),
    INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_time_bucket_minmax time_bucket TYPE minmax GRANULARITY 1
)
ENGINE = {ReplacingMergeTree(METRICS4_SERIES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED, ver="timestamp")}
PARTITION BY toStartOfWeek(original_expiry_timestamp)
ORDER BY (team_id, metric_name, series_fingerprint, time_bucket)
TTL original_expiry_timestamp
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRICS4_NAMES_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS4_NAMES_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `original_expiry_timestamp` SimpleAggregateFunction(max, DateTime64(6))
)
ENGINE = {AggregatingMergeTree(METRICS4_NAMES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, time_bucket, metric_name, original_expiry_time_bucket)
TTL original_expiry_timestamp
SETTINGS index_granularity = 8192
"""


def METRICS4_ATTRIBUTES_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS4_ATTRIBUTES_TABLE_NAME}
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
ENGINE = {AggregatingMergeTree(METRICS4_ATTRIBUTES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_time_bucket)
ORDER BY (team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)
TTL original_expiry_time_bucket
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRICS2_INPUT_TO_METRICS4_SAMPLES_MV() -> str:
    db = _db()
    group_arrays = ",\n".join(f"    groupArray({name}) AS {name}_arr" for name, _ in METRICS4_POINT_ARRAY_COLUMNS)
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{METRICS4_SAMPLES_TABLE_NAME} TO {db}.{METRICS4_SAMPLES_TABLE_NAME}
AS SELECT
    team_id,
    metric_name,
    toDateTime(toStartOfHour(timestamp)) AS time_bucket,
    series_fingerprint,
    toDate32({METRICS4_EXPIRY_EXPR}) AS original_expiry_date,
    any(resource_fingerprint) AS resource_fingerprint,
    any(service_name) AS service_name,
    any(metric_type) AS metric_type,
    any(unit) AS unit,
    any(aggregation_temporality) AS aggregation_temporality,
    max(toUInt8(is_monotonic)) AS is_monotonic,
    max(toUInt8(has_labels)) AS has_labels,
    any(instrumentation_scope) AS instrumentation_scope,
    anyLast(histogram_bounds) AS histogram_bounds,
    any(_topic) AS _topic,
{group_arrays}
FROM {db}.{METRICS2_INPUT_TABLE_NAME}
GROUP BY
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    original_expiry_date
"""


def METRICS2_INPUT_TO_METRICS4_SERIES_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{METRICS4_SERIES_TABLE_NAME} TO {db}.{METRICS4_SERIES_TABLE_NAME}
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
    timestamp,
    {METRICS4_EXPIRY_EXPR} AS original_expiry_timestamp
FROM {db}.{METRICS2_INPUT_TABLE_NAME}
WHERE has_labels
"""


def METRICS2_INPUT_TO_METRICS4_NAMES_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{METRICS4_NAMES_TABLE_NAME} TO {db}.{METRICS4_NAMES_TABLE_NAME}
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
    toStartOfHour({METRICS4_EXPIRY_EXPR}) AS original_expiry_time_bucket,
    maxSimpleState({METRICS4_EXPIRY_EXPR}) AS original_expiry_timestamp
FROM {db}.{METRICS2_INPUT_TABLE_NAME}
WHERE has_labels
GROUP BY team_id, time_bucket, metric_name, original_expiry_time_bucket
"""


def _metrics4_attributes_mv(view_suffix: str, source_map: str, attribute_type: str, filter_long_pairs: bool) -> str:
    db = _db()
    attributes_expr = (
        f"mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), {source_map})"
        if filter_long_pairs
        else source_map
    )
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_INPUT_TABLE_NAME}_to_{view_suffix} TO {db}.{METRICS4_ATTRIBUTES_TABLE_NAME}
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
        toStartOfInterval({METRICS4_EXPIRY_EXPR}, toIntervalHour(1)) AS original_expiry_time_bucket,
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


def METRICS2_INPUT_TO_METRICS4_ATTRIBUTES_MV() -> str:
    return _metrics4_attributes_mv(METRICS4_ATTRIBUTES_TABLE_NAME, "attributes", "metric", filter_long_pairs=True)


def METRICS2_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV() -> str:
    return _metrics4_attributes_mv(
        "metrics4_resource_attributes", "resource_attributes", "resource", filter_long_pairs=False
    )
