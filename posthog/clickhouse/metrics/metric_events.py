from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

# Event-per-occurrence metrics ("application metrics"): one row per emission,
# high-cardinality attributes, trace-connected, aggregated at QUERY time. This is
# deliberately NOT a pre-aggregated TSDB like `metrics1` (which holds rolled-up
# OTLP/Prometheus samples) — each row is a discrete event carrying its trace_id
# so a spike can pivot straight to the trace behind it. Lives on the logs
# ClickHouse cluster next to logs/traces so that pivot is a same-cluster join.
#
# kind ∈ {counter, gauge, distribution}; at query time:
#   counter      -> count()/sum(value)
#   gauge        -> argMax(value, timestamp)
#   distribution -> quantile(value)  (raw values, no pre-bucketed histograms)

TABLE_NAME = "metric_events1"
DISTRIBUTED_TABLE_NAME = "metric_events"


def METRIC_EVENTS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now64(6) CODEC(DoubleDelta, ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `trace_flags` Int32 CODEC(ZSTD(1)),
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `metric_name` LowCardinality(String) CODEC(ZSTD(1)),
    `kind` LowCardinality(String) CODEC(ZSTD(1)),
    `value` Float64 CODEC(Gorilla, ZSTD(1)),
    `unit` LowCardinality(String) CODEC(ZSTD(1)),
    `resource_attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    INDEX idx_metric_name_set metric_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_kind_set kind TYPE set(10) GRANULARITY 1,
    INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(timestamp)
ORDER BY (team_id, metric_name, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS
    index_granularity = 8192,
    ttl_only_drop_parts = 1
"""


def METRIC_EVENTS_DISTRIBUTED_TABLE_SQL():
    return "CREATE TABLE IF NOT EXISTS {database}.{distributed} AS {database}.{table_name} ENGINE = {engine}".format(
        distributed=DISTRIBUTED_TABLE_NAME,
        table_name=TABLE_NAME,
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
    )
