"""Experimental array-per-series-hour layout for the metrics2 data points.

`metrics2_agg` is an AggregatingMergeTree keyed by
`(team_id, metric_name, time_bucket, series_fingerprint)`. One row holds every
point of one series in one hour, as parallel arrays (`timestamp_arr`,
`value_arr`, ...). `metrics2_input_to_metrics_agg` fills it from the same
`metrics2_input` rows that feed `metrics2`, so both tables hold the same points.
`metrics2_flat` is a VIEW that ARRAY JOINs the arrays back into the `metrics2`
column layout, so the existing readers run against it unchanged. `metrics2_flat_idx`
does the same with one `arrayJoin(arrayEnumerate(...))` index and `arr[idx]`
element reads, so a query that needs two arrays does not read all twelve.

Why the parallel arrays stay aligned: inside one insert block, every
`groupArray(col)` for one key sees the same rows in the same order, so index
`i` of every array is the same source point. On merge, the engine applies
`groupArrayArray` (concatenation) to every array column of the equal-key rows in
the same sequence, so alignment survives. Nothing sorts the arrays by time, so
readers must not assume time order. `ARRAY JOIN` over several arrays throws when
their lengths differ, so misalignment fails loudly instead of silently.

This module is a spike: it is not part of `schema.py`, the migrations, or the
HCL layer. `products/metrics/scripts/metrics_agg_bench.py` benchmarks it and the
metrics pytest suite can run against a view via `METRICS_ARRAY_VIEW`.
"""

from django.conf import settings

from posthog.clickhouse.table_engines import AggregatingMergeTree, ReplicationScheme

from .metrics2 import METRICS2_INPUT_TABLE_NAME

METRICS2_AGG_TABLE_NAME = "metrics2_agg"
METRICS2_AGG_MV_NAME = f"{METRICS2_INPUT_TABLE_NAME}_to_metrics_agg"
METRICS2_FLAT_VIEW_NAME = "metrics2_flat"
METRICS2_FLAT_INDEXED_VIEW_NAME = "metrics2_flat_idx"

# (metrics2 column, element type) for every per-point column that becomes an array.
POINT_ARRAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("timestamp", "DateTime64(6)"),
    ("value", "Float64"),
    ("count", "UInt64"),
    ("observed_timestamp", "DateTime64(6)"),
    ("original_expiry_timestamp", "DateTime64(6)"),
    ("histogram_bounds", "Array(Float64)"),
    ("histogram_counts", "Array(UInt64)"),
    ("trace_id", "String"),
    ("span_id", "String"),
    ("trace_flags", "Int32"),
    ("_partition", "UInt32"),
    ("_offset", "UInt64"),
)

# Codecs for the arrays that benefit from a time-series codec. Gorilla and
# DoubleDelta apply to the element stream of an Array column; the harness
# falls back to ZSTD when the server rejects them.
ARRAY_CODECS: dict[str, str] = {
    "timestamp": "CODEC(DoubleDelta, ZSTD(1))",
    "observed_timestamp": "CODEC(DoubleDelta, ZSTD(1))",
    "original_expiry_timestamp": "CODEC(DoubleDelta, ZSTD(1))",
    "value": "CODEC(Gorilla, ZSTD(1))",
    "count": "CODEC(T64, ZSTD(1))",
}


def _db() -> str:
    return settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE


def _array_column_defs(codecs: dict[str, str]) -> str:
    lines = []
    for name, element_type in POINT_ARRAY_COLUMNS:
        codec = f" {codecs[name]}" if name in codecs else ""
        lines.append(f"    `{name}_arr` SimpleAggregateFunction(groupArrayArray, Array({element_type})){codec}")
    return ",\n".join(lines)


def METRICS2_AGG_TABLE_SQL(codecs: dict[str, str] | None = None) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_db()}.{METRICS2_AGG_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `time_bucket` DateTime,
    `series_fingerprint` UInt64 CODEC(Delta, Default),
    `original_expiry_date` Date32,
    `resource_fingerprint` SimpleAggregateFunction(any, UInt64),
    `service_name` SimpleAggregateFunction(any, LowCardinality(String)),
    `metric_type` SimpleAggregateFunction(any, LowCardinality(String)),
    `has_labels` SimpleAggregateFunction(max, UInt8),
    `unit` SimpleAggregateFunction(any, LowCardinality(String)),
    `aggregation_temporality` SimpleAggregateFunction(any, LowCardinality(String)),
    `is_monotonic` SimpleAggregateFunction(max, UInt8),
    `instrumentation_scope` SimpleAggregateFunction(any, String),
    `_topic` SimpleAggregateFunction(any, String),
{_array_column_defs(ARRAY_CODECS if codecs is None else codecs)},
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_trace_id_bf trace_id_arr TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {AggregatingMergeTree(METRICS2_AGG_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY original_expiry_date
ORDER BY (team_id, metric_name, time_bucket, series_fingerprint)
TTL original_expiry_date
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRICS2_INPUT_TO_METRICS_AGG_MV() -> str:
    db = _db()
    group_arrays = ",\n".join(f"    groupArray({name}) AS {name}_arr" for name, _ in POINT_ARRAY_COLUMNS)
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{METRICS2_AGG_MV_NAME} TO {db}.{METRICS2_AGG_TABLE_NAME}
AS SELECT
    team_id,
    metric_name,
    toDateTime(toStartOfHour(timestamp)) AS time_bucket,
    series_fingerprint,
    toDate32(original_expiry_timestamp) AS original_expiry_date,
    any(resource_fingerprint) AS resource_fingerprint,
    any(service_name) AS service_name,
    any(metric_type) AS metric_type,
    max(toUInt8(has_labels)) AS has_labels,
    any(unit) AS unit,
    any(aggregation_temporality) AS aggregation_temporality,
    max(toUInt8(is_monotonic)) AS is_monotonic,
    any(instrumentation_scope) AS instrumentation_scope,
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


_FLAT_SERIES_COLUMNS = """
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    resource_fingerprint,
    service_name,
    metric_type,
    toBool(has_labels) AS has_labels,
    unit,
    aggregation_temporality,
    toBool(is_monotonic) AS is_monotonic,
    instrumentation_scope,
    _topic"""


def METRICS2_FLAT_VIEW_SQL() -> str:
    db = _db()
    point_columns = ",\n".join(f"    {name}" for name, _ in POINT_ARRAY_COLUMNS)
    array_join = ",\n".join(f"    {name}_arr AS {name}" for name, _ in POINT_ARRAY_COLUMNS)
    return f"""
CREATE VIEW IF NOT EXISTS {db}.{METRICS2_FLAT_VIEW_NAME}
AS SELECT{_FLAT_SERIES_COLUMNS},
{point_columns}
FROM {db}.{METRICS2_AGG_TABLE_NAME}
ARRAY JOIN
{array_join}
"""


def METRICS2_FLAT_INDEXED_VIEW_SQL() -> str:
    db = _db()
    point_columns = ",\n".join(f"    {name}_arr[idx] AS {name}" for name, _ in POINT_ARRAY_COLUMNS)
    return f"""
CREATE VIEW IF NOT EXISTS {db}.{METRICS2_FLAT_INDEXED_VIEW_NAME}
AS SELECT{_FLAT_SERIES_COLUMNS},
    arrayJoin(arrayEnumerate(timestamp_arr)) AS idx,
{point_columns}
FROM {db}.{METRICS2_AGG_TABLE_NAME}
"""
