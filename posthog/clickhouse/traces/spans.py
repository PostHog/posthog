from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

from .trace_attributes import (
    TABLE_NAME as TRACE_ATTRIBUTES_TABLE_NAME,
    TABLE_NAME_V2 as TRACE_ATTRIBUTES_TABLE_NAME_V2,
)

TABLE_NAME = "trace_spans"
KAFKA_METRICS_TABLE_NAME = "trace_spans_kafka_metrics"
KAFKA_TABLE_NAME = "kafka_trace_spans_avro"
KAFKA_NAMED_COLLECTION = "warpstream_traces"
KAFKA_TOPIC = "clickhouse_traces"
KAFKA_GROUP = "clickhouse-traces-avro"


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
    INDEX idx_trace_bloom_part trace_id TYPE bloom_filter(0.00001) GRANULARITY 99999,
    INDEX idx_span_id_bloom_part span_id TYPE bloom_filter(0.00001) GRANULARITY 99999,

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

    PROJECTION projection_index_span_id
    (
        SELECT _part_offset
        ORDER BY span_id
    ),

    PROJECTION projection_index_trace_id
    (
        SELECT _part_offset
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


def _trace_attributes_mv(view_name: str, dest_table: str, attribute_type: str, inner_select: str):
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{view_name} TO {db}.{dest_table}
(
    `team_id` Int32,
    `original_expiry_time_bucket` DateTime64(0),
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    original_expiry_time_bucket,
    time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    '{attribute_type}' AS attribute_type,
    attribute_count
FROM
(
{inner_select}
)
"""


def _span_attributes_inner():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""    SELECT
        team_id AS team_id,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {db}.{TABLE_NAME}
    GROUP BY
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute"""


def _resource_attributes_inner():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""    SELECT
        team_id AS team_id,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {db}.{TABLE_NAME}
    GROUP BY
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute"""


def _span_name_inner():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""    SELECT
        team_id AS team_id,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        'name' AS attribute_key,
        name AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {db}.{TABLE_NAME}
    GROUP BY
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        name"""


def TRACE_SPAN_TO_ATTRIBUTES_MV():
    return _trace_attributes_mv(
        "trace_span_to_attributes", TRACE_ATTRIBUTES_TABLE_NAME, "span_attribute", _span_attributes_inner()
    )


def TRACE_SPAN_TO_RESOURCE_ATTRIBUTES_MV():
    return _trace_attributes_mv(
        "trace_span_to_resource_attributes",
        TRACE_ATTRIBUTES_TABLE_NAME,
        "span_resource_attribute",
        _resource_attributes_inner(),
    )


def TRACE_SPAN_TO_SPAN_ATTRIBUTES_MV():
    return _trace_attributes_mv(
        "trace_span_to_span_attributes", TRACE_ATTRIBUTES_TABLE_NAME, "span", _span_name_inner()
    )


def TRACE_SPAN_TO_ATTRIBUTES2_MV():
    return _trace_attributes_mv(
        "trace_span_to_attributes2", TRACE_ATTRIBUTES_TABLE_NAME_V2, "span_attribute", _span_attributes_inner()
    )


def TRACE_SPAN_TO_RESOURCE_ATTRIBUTES2_MV():
    return _trace_attributes_mv(
        "trace_span_to_resource_attributes2",
        TRACE_ATTRIBUTES_TABLE_NAME_V2,
        "span_resource_attribute",
        _resource_attributes_inner(),
    )


def TRACE_SPAN_TO_SPAN_ATTRIBUTES2_MV():
    return _trace_attributes_mv(
        "trace_span_to_span_attributes2", TRACE_ATTRIBUTES_TABLE_NAME_V2, "span", _span_name_inner()
    )


def KAFKA_TRACE_SPANS_AVRO_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{KAFKA_TABLE_NAME}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `parent_span_id` String,
    `trace_state` String,
    `name` String,
    `kind` Int32,
    `flags` Int32,
    `timestamp` DateTime64(6),
    `end_time` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `service_name` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `instrumentation_scope` String,
    `attributes` Map(LowCardinality(String), String),
    `dropped_attributes_count` Int32,
    `events` Array(String),
    `dropped_events_count` Int32,
    `links` Array(String),
    `dropped_links_count` Int32,
    `status_code` Int32
)
ENGINE = {kafka_engine(topic=KAFKA_TOPIC, group=KAFKA_GROUP, serialization="Avro", named_collection=KAFKA_NAMED_COLLECTION)}
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 8,
    kafka_poll_timeout_ms = 3000,
    kafka_poll_max_batch_size = 1000
"""


def KAFKA_TRACE_SPANS_AVRO_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.{KAFKA_TABLE_NAME}_mv TO {db}.{TABLE_NAME}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `parent_span_id` String,
    `trace_state` String,
    `name` String,
    `kind` Int8,
    `flags` UInt32,
    `timestamp` DateTime64(6),
    `end_time` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `service_name` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `instrumentation_scope` String,
    `attributes_map_str` Map(LowCardinality(String), String),
    `dropped_attributes_count` UInt32,
    `events` Array(String),
    `dropped_events_count` UInt32,
    `links` Array(String),
    `dropped_links_count` UInt32,
    `status_code` Int16,
    `team_id` Int32,
    `original_expiry_timestamp` DateTime64(6)
)
AS SELECT
    * EXCEPT (attributes, resource_attributes, kind, flags, dropped_attributes_count, dropped_events_count, dropped_links_count, status_code),
    toInt8(kind) AS kind,
    toUInt32(flags) AS flags,
    toUInt32(dropped_attributes_count) AS dropped_attributes_count,
    toUInt32(dropped_events_count) AS dropped_events_count,
    toUInt32(dropped_links_count) AS dropped_links_count,
    toInt16(status_code) AS status_code,
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    observed_timestamp + toIntervalDay(toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))) AS original_expiry_timestamp,
    _partition,
    _topic,
    _offset,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')], toInt64(0)) AS _bytes_uncompressed,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_compressed')], toInt64(0)) AS _bytes_compressed
FROM {db}.{KAFKA_TABLE_NAME}
"""


def TRACE_SPANS_KAFKA_METRICS_TABLE_SQL():
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
ENGINE = {MergeTreeEngine(KAFKA_METRICS_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
ORDER BY (_topic, _partition)
SETTINGS
    index_granularity = 8192
"""


def TRACE_SPANS_TO_KAFKA_METRICS_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.trace_spans_to_kafka_metrics_mv TO {db}.{KAFKA_METRICS_TABLE_NAME}
(
    `_partition` UInt64,
    `_topic` LowCardinality(String),
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(6)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(6)),
    `max_created_at` SimpleAggregateFunction(max, DateTime),
    `max_lag` SimpleAggregateFunction(max, Decimal(18, 6))
)
AS SELECT
    _partition,
    _topic,
    maxSimpleState(_offset) AS max_offset,
    maxSimpleState(observed_timestamp) AS max_observed_timestamp,
    maxSimpleState(timestamp) AS max_timestamp,
    maxSimpleState(now()) AS max_created_at,
    maxSimpleState(now() - observed_timestamp) AS max_lag
FROM {db}.{TABLE_NAME}
GROUP BY _partition, _topic
"""
