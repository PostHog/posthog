from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplacingMergeTree, ReplicationScheme

# Raw, un-aggregated metrics stored as a TSDB series/samples split (not the
# fat one-row-per-event shape logs/traces use — a metric sample is a single
# number, so inlining the label maps on every row would dwarf the data ~100x).
#
# - metric_series: one row per unique (metric, label-set), labels stored ONCE,
#   keyed by series_fingerprint. Deduped via ReplacingMergeTree.
# - metric_samples: the hot table — tiny rows (series_fingerprint + timestamp +
#   value), plus an inline trace_id so a spike can still pivot to its trace (empty
#   for most points, so it compresses to ~nothing). Joined to metric_series on
#   series_fingerprint at query time.
#
# series_fingerprint is assigned ONCE at ingest (rust/capture-logs computes it over
# the canonical label set and ships it in the Avro payload); the ingest MVs store it
# verbatim and never recompute it. This is the TSDB / Snuffle-default approach — the
# storage engine must not compute identity, or two independent MVs diverge (and the
# stored-map MV context corrupts the hash). See docs/internal/metrics for the history.
#
# Distinct from `metrics1` (pre-aggregated rollups for dashboards/alerts): this
# keeps every raw sample, for exact quantiles, per-emission drill-down, and the
# metric->trace pivot. Lives on the logs ClickHouse cluster next to logs/traces.
#
# aggregation_temporality/is_monotonic live on the series (rate() needs them to
# know whether to diff) but are NOT in the fingerprint — a collector config change
# should update the series via the Replacing dedup, not re-key it. Histogram
# bucket arrays stay on the sample row, self-contained: exponential histograms
# can rescale their buckets between emissions, so bounds can't live on the
# deduped series row without silently misaligning a sample's counts.

SAMPLES_TABLE_NAME = "metric_samples1"
SAMPLES_DISTRIBUTED_TABLE_NAME = "metric_samples"
SERIES_TABLE_NAME = "metric_series1"
SERIES_DISTRIBUTED_TABLE_NAME = "metric_series"


def METRIC_SERIES_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{SERIES_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(DoubleDelta),
    `metric_type` LowCardinality(String),
    `unit` LowCardinality(String),
    `aggregation_temporality` LowCardinality(String),
    `is_monotonic` Bool DEFAULT false,
    `service_name` LowCardinality(String),
    `resource_attributes` Map(LowCardinality(String), String),
    `attributes` Map(LowCardinality(String), String),
    `last_seen` DateTime64(6) CODEC(DoubleDelta),
    INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {ReplacingMergeTree(SERIES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED, ver="last_seen")}
ORDER BY (team_id, metric_name, series_fingerprint)
TTL toDateTime(last_seen) + INTERVAL 90 DAY DELETE
SETTINGS index_granularity = 8192
"""


def METRIC_SAMPLES_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{SAMPLES_TABLE_NAME}
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(DoubleDelta),
    `timestamp` DateTime64(6) CODEC(DoubleDelta),
    `value` Float64 CODEC(Gorilla),
    `count` UInt64 DEFAULT 1,
    `histogram_bounds` Array(Float64),
    `histogram_counts` Array(UInt64),
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {MergeTreeEngine(SAMPLES_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(timestamp)
ORDER BY (team_id, metric_name, series_fingerprint, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1
"""


def _distributed_sql(distributed_name: str, data_table: str) -> str:
    return "CREATE TABLE IF NOT EXISTS {database}.{distributed} AS {database}.{table_name} ENGINE = {engine}".format(
        distributed=distributed_name,
        table_name=data_table,
        engine=Distributed(data_table=data_table, cluster=settings.CLICKHOUSE_LOGS_CLUSTER),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
    )


def METRIC_SERIES_DISTRIBUTED_TABLE_SQL():
    return _distributed_sql(SERIES_DISTRIBUTED_TABLE_NAME, SERIES_TABLE_NAME)


def METRIC_SAMPLES_DISTRIBUTED_TABLE_SQL():
    return _distributed_sql(SAMPLES_DISTRIBUTED_TABLE_NAME, SAMPLES_TABLE_NAME)
