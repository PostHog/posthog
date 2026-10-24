from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

from .trace_attributes import TABLE_NAME as TRACE_ATTRIBUTES_TABLE_NAME

TABLE_NAME = "trace_spans"


def TRACE_SPANS_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `time_bucket` DateTime MATERIALIZED toStartOfInterval(timestamp, toIntervalHour(4)),
    `original_expiry_timestamp` DateTime64(6),
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `parent_span_id` String,
    `is_root_span` Bool MATERIALIZED replaceAll(trimRight(parent_span_id, '='), 'A', '') = '',
    `trace_state` String,
    `name` LowCardinality(String),
    `kind` Int8,
    `flags` UInt32,
    `timestamp` DateTime64(6),
    `end_time` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6) MATERIALIZED now(),
    `duration_nano` UInt64 MATERIALIZED toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000,
    `status_code` Int16,
    `service_name` LowCardinality(String),
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes),
    `instrumentation_scope` String,
    `attributes_map_str` Map(LowCardinality(String), String),
    `attributes` Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
    `dropped_attributes_count` UInt32,
    `dropped_events_count` UInt32,
    `dropped_links_count` UInt32,
    `events` Array(String),
    `links` Array(String),

    -- kafka metadata
    `_partition` UInt32,
    `_topic` String,
    `_offset` UInt64,
    `_bytes_uncompressed` UInt64,
    `_bytes_compressed` UInt64,
    `_record_count` UInt64,

    INDEX idx_name name TYPE ngrambf_v1(4, 5000, 2, 0) GRANULARITY 16,
    INDEX idx_kind kind TYPE minmax GRANULARITY 4,
    INDEX idx_duration duration_nano TYPE minmax GRANULARITY 1,
    INDEX idx_status_code status_code TYPE minmax GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 16,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 16,
    INDEX idx_trace_bloom_part_v2 trace_id TYPE bloom_filter(0.05) GRANULARITY 99999,
    INDEX idx_span_id_bloom_part_v2 span_id TYPE bloom_filter(0.05) GRANULARITY 99999,

    -- Powers the Spans-view sparkline (spans per minute via sum(event_count)). is_root_span is a
    -- projection dimension so the Traces-view sparkline (distinct traces per minute) can serve from
    -- this projection too via sumIf(event_count, is_root_span = 1) — one root span per trace —
    -- instead of the uniqExactIf(trace_id, is_root_span = 1) raw scan it currently runs.
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            resource_fingerprint,
            is_root_span,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            resource_fingerprint,
            is_root_span
    ),

    PROJECTION projection_index_team_span_id
    (
        SELECT team_id, _part_offset
        ORDER BY span_id
    ),

    PROJECTION projection_index_team_trace_id
    (
        SELECT team_id, _part_offset
        ORDER BY trace_id
    )
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
TTL original_expiry_timestamp
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    allow_part_offset_column_in_projections = 1,
    map_serialization_version = 'with_buckets'
"""


def TRACE_SPANS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.trace_spans_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )


def TRACE_ATTRIBUTES_DISTRIBUTED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {database}.trace_attributes_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TRACE_ATTRIBUTES_TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TRACE_ATTRIBUTES_TABLE_NAME,
    )
