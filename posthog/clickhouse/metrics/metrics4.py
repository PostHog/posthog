"""Define the metrics4 ClickHouse tables and materialized views.

`metrics4_samples` groups points by series, hour, and expiry date. A complete
merge produces one row for each key. The table stores each point field in a
parallel array. The insert view and background merges keep at most 10,000 points
in each row. Readers combine partial rows and sort the points by timestamp. The
PromQL bridge already creates the same array shape from `metrics2`.

After a merge, `metrics4_series` keeps one label row for each active series-hour
in an expiry partition. `metrics4_names` stores hourly metric names.
`metrics4_attributes` stores hourly metric and resource attributes. Readers use
the last two tables for name and attribute selectors.

`metrics4_input` supplies `original_expiry_timestamp` to each view. The Kafka
view calculates this timestamp from the sample timestamp. The tables derive
their expiry values from it. The default retention period is 30 days.

The aggregate views process one input block at a time. The Kafka table flushes
one block every 30 seconds. Larger blocks let `metrics4_samples` combine more
points before it writes a part. `metrics4_series` uses an index granularity of
1,024. This smaller granularity reduces the rows that a primary-key lookup reads
from a new part.

ClickHouse gives each parallel `groupArray` function the same input order for
one block. Therefore, the same array index identifies all fields of one point.
During a merge, ClickHouse uses the same row sequence for each array.
`groupArrayArray` keeps at most 10,000 elements from that sequence. `ARRAY JOIN`
requires all parallel arrays to have the same length.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplacingMergeTree, ReplicationScheme

from .metrics2 import kafka_metrics_avro_mv_select, kafka_metrics_avro_table_sql, metrics_input_table_sql

KAFKA_METRICS4_TABLE_NAME = "kafka_metrics_avro4"
KAFKA_METRICS4_GROUP = "clickhouse-metrics-avro4"
KAFKA_METRICS4_FLUSH_INTERVAL_MS = 30_000
KAFKA_METRICS4_MAX_BLOCK_SIZE = 1_000_000
METRICS4_INPUT_TABLE_NAME = "metrics4_input"
METRICS4_SAMPLES_TABLE_NAME = "metrics4_samples"
METRICS4_SERIES_TABLE_NAME = "metrics4_series"
METRICS4_NAMES_TABLE_NAME = "metrics4_names"
METRICS4_ATTRIBUTES_TABLE_NAME = "metrics4_attributes"
WRITABLE_METRICS4_SAMPLES_TABLE_NAME = "writable_metrics4_samples"
WRITABLE_METRICS4_SERIES_TABLE_NAME = "writable_metrics4_series"
WRITABLE_METRICS4_NAMES_TABLE_NAME = "writable_metrics4_names"
WRITABLE_METRICS4_ATTRIBUTES_TABLE_NAME = "writable_metrics4_attributes"
METRICS4_MAX_SAMPLES_PER_SERIES_HOUR = 10_000

# Each tuple maps an input column to its metrics4 array element type.
METRICS4_POINT_ARRAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("timestamp", "DateTime64(6)"),
    ("observed_timestamp", "DateTime64(6)"),
    ("value", "Float64"),
    ("count", "UInt64"),
    ("histogram_counts", "Array(UInt64)"),
    ("trace_id", "String"),
    ("span_id", "String"),
    ("trace_flags", "Int32"),
)

# ClickHouse applies each codec to the continuous stream of array elements.
# Each array keeps its insert order. The delta codecs compress adjacent values.
# T64 and Gorilla can process values without a sort.
_ARRAY_CODECS: dict[str, str] = {
    "timestamp": " CODEC(DoubleDelta, Default)",
    "observed_timestamp": " CODEC(DoubleDelta, Default)",
    "value": " CODEC(Gorilla, Default)",
    "count": " CODEC(T64, Default)",
    "histogram_counts": " CODEC(T64, Default)",
}


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def KAFKA_METRICS_AVRO4_TABLE_SQL() -> str:
    return kafka_metrics_avro_table_sql(
        KAFKA_METRICS4_TABLE_NAME,
        KAFKA_METRICS4_GROUP,
        flush_interval_ms=KAFKA_METRICS4_FLUSH_INTERVAL_MS,
        max_block_size=KAFKA_METRICS4_MAX_BLOCK_SIZE,
    )


def METRICS4_INPUT_TABLE_SQL() -> str:
    return metrics_input_table_sql(METRICS4_INPUT_TABLE_NAME)


def KAFKA_METRICS_AVRO4_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_METRICS4_TABLE_NAME}_mv TO {db}.{METRICS4_INPUT_TABLE_NAME}
AS {kafka_metrics_avro_mv_select(KAFKA_METRICS4_TABLE_NAME)}
"""


def _writable_table_sql(table_name: str, data_table_name: str, columns: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{table_name}
(
{columns}
)
ENGINE = {Distributed(data_table=data_table_name, cluster=settings.CLICKHOUSE_LOGS_CLUSTER)}
"""


def WRITABLE_METRICS4_SAMPLES_TABLE_SQL() -> str:
    arrays = ",\n".join(
        f"    `{name}_arr` SimpleAggregateFunction(groupArrayArray({METRICS4_MAX_SAMPLES_PER_SERIES_HOUR}), Array({element_type}))"
        for name, element_type in METRICS4_POINT_ARRAY_COLUMNS
    )
    return _writable_table_sql(
        WRITABLE_METRICS4_SAMPLES_TABLE_NAME,
        METRICS4_SAMPLES_TABLE_NAME,
        f"""    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime,
    `series_fingerprint` UInt64,
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
{arrays}""",
    )


def WRITABLE_METRICS4_SERIES_TABLE_SQL() -> str:
    return _writable_table_sql(
        WRITABLE_METRICS4_SERIES_TABLE_NAME,
        METRICS4_SERIES_TABLE_NAME,
        """    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64,
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
    `original_expiry_timestamp` DateTime64(6)""",
    )


def WRITABLE_METRICS4_NAMES_TABLE_SQL() -> str:
    return _writable_table_sql(
        WRITABLE_METRICS4_NAMES_TABLE_NAME,
        METRICS4_NAMES_TABLE_NAME,
        """    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `original_expiry_timestamp` SimpleAggregateFunction(max, DateTime64(6))""",
    )


def WRITABLE_METRICS4_ATTRIBUTES_TABLE_SQL() -> str:
    return _writable_table_sql(
        WRITABLE_METRICS4_ATTRIBUTES_TABLE_NAME,
        METRICS4_ATTRIBUTES_TABLE_NAME,
        """    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)""",
    )


def METRICS4_SAMPLES_TABLE_SQL() -> str:
    arrays = ",\n".join(
        f"    `{name}_arr` SimpleAggregateFunction(groupArrayArray({METRICS4_MAX_SAMPLES_PER_SERIES_HOUR}), Array({element_type})){_ARRAY_CODECS.get(name, '')}"
        for name, element_type in METRICS4_POINT_ARRAY_COLUMNS
    )
    # One merged row contains up to 10,000 points for one series-hour and expiry date.
    # A 128-row granule can contain many series from one insert.
    # A primary-key filter cannot skip individual rows in that granule.
    # The granule can contain multiple metric names and time buckets.
    # The time_bucket minmax index lets an hour filter skip the complete granule.
    # The metrics2 table uses idx_timestamp_minmax for the same purpose.
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
    index_granularity = 1024,
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


def METRICS4_INPUT_TO_METRICS4_SAMPLES_MV() -> str:
    db = _db()
    group_arrays = ",\n".join(
        f"    groupArray({METRICS4_MAX_SAMPLES_PER_SERIES_HOUR})({name}) AS {name}_arr"
        for name, _ in METRICS4_POINT_ARRAY_COLUMNS
    )
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS4_INPUT_TABLE_NAME}_to_{METRICS4_SAMPLES_TABLE_NAME} TO {db}.{WRITABLE_METRICS4_SAMPLES_TABLE_NAME}
AS SELECT
    team_id,
    metric_name,
    toDateTime(toStartOfHour(timestamp)) AS time_bucket,
    series_fingerprint,
    toDate32(original_expiry_timestamp) AS original_expiry_date,
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
FROM {db}.{METRICS4_INPUT_TABLE_NAME}
GROUP BY
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    original_expiry_date
"""


def METRICS4_INPUT_TO_METRICS4_SERIES_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS4_INPUT_TABLE_NAME}_to_{METRICS4_SERIES_TABLE_NAME} TO {db}.{WRITABLE_METRICS4_SERIES_TABLE_NAME}
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
    original_expiry_timestamp
FROM {db}.{METRICS4_INPUT_TABLE_NAME}
WHERE has_labels
"""


def METRICS4_INPUT_TO_METRICS4_NAMES_MV() -> str:
    db = _db()
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS4_INPUT_TABLE_NAME}_to_{METRICS4_NAMES_TABLE_NAME} TO {db}.{WRITABLE_METRICS4_NAMES_TABLE_NAME}
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
FROM {db}.{METRICS4_INPUT_TABLE_NAME} AS input
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
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS4_INPUT_TABLE_NAME}_to_{view_suffix} TO {db}.{WRITABLE_METRICS4_ATTRIBUTES_TABLE_NAME}
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
    FROM {db}.{METRICS4_INPUT_TABLE_NAME}
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


def METRICS4_INPUT_TO_METRICS4_ATTRIBUTES_MV() -> str:
    return _metrics4_attributes_mv(METRICS4_ATTRIBUTES_TABLE_NAME, "attributes", "metric", filter_long_pairs=True)


def METRICS4_INPUT_TO_METRICS4_RESOURCE_ATTRIBUTES_MV() -> str:
    return _metrics4_attributes_mv(
        "metrics4_resource_attributes", "resource_attributes", "resource", filter_long_pairs=False
    )
