from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

TABLE_NAME = "spans"

TTL = (
    lambda: "TTL timestamp + toIntervalHour(25) TO DISK 's3'" if settings.CLICKHOUSE_LOGS_ENABLE_STORAGE_POLICY else ""
)
STORAGE_POLICY = lambda: "tiered" if settings.CLICKHOUSE_LOGS_ENABLE_STORAGE_POLICY else "default"


def SPANS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `original_expiry_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `parent_span_id` String CODEC(ZSTD(1)),
    `trace_state` String CODEC(ZSTD(1)),
    `name` LowCardinality(String) CODEC(ZSTD(1)),
    `kind` Int8 CODEC(T64, ZSTD(1)),
    `flags` UInt32 CODEC(T64, ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `end_time` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `observed_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
    `duration_nano` UInt64 MATERIALIZED toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000 CODEC(T64, ZSTD(1)),
    `status_code` Int16 CODEC(T64, ZSTD(1)),
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `resource_attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `attributes` Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)) CODEC(ZSTD(1)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)) CODEC(ZSTD(1)),
    `dropped_attributes_count` UInt32 CODEC(ZSTD(1)),
    `dropped_events_count` UInt32 CODEC(ZSTD(1)),
    `dropped_links_count` UInt32 CODEC(ZSTD(1)),
    `events` Array(String) CODEC(ZSTD(2)),
    `links` Array(String) CODEC(ZSTD(1)),

    -- kafka metadata
    `_partition` UInt32 CODEC(DoubleDelta, ZSTD(1)),
    `_topic` String,
    `_offset` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_bytes_uncompressed` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_bytes_compressed` UInt64 CODEC(DoubleDelta, ZSTD(1)),
    `_record_count` UInt64 CODEC(DoubleDelta, ZSTD(1)),

    INDEX idx_trace_id trace_id TYPE tokenbf_v1(10000, 5, 0) GRANULARITY 1,
    INDEX idx_span_id span_id TYPE tokenbf_v1(5000, 5, 0) GRANULARITY 1,
    INDEX idx_name name TYPE ngrambf_v1(4, 5000, 2, 0) GRANULARITY 1,
    INDEX idx_kind kind TYPE minmax GRANULARITY 4,
    INDEX idx_duration duration_nano TYPE minmax GRANULARITY 1,
    INDEX idx_status_code status_code TYPE minmax GRANULARITY 1,
    INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
{TTL()}
SETTINGS
    storage_policy = '{STORAGE_POLICY()}',
    allow_remote_fs_zero_copy_replication = 1,
    allow_experimental_reverse_key = 1,
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    add_minmax_index_for_numeric_columns = 1
"""


def SPANS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.spans_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=f"{TABLE_NAME}",
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )
