from django.conf import settings

from posthog.clickhouse.client.execute import clickhouse_supports_reverse_key
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

from .log_attributes2 import TABLE_NAME as LOG_ATTRIBUTES_TABLE_NAME
from .log_attributes3 import TABLE_NAME as LOG_ATTRIBUTES3_TABLE_NAME

TABLE_NAME = "logs34"
KAFKA_TABLE_NAME = "kafka_logs_avro"
KAFKA_NAMED_COLLECTION = "warpstream_logs"
KAFKA_TOPIC = "clickhouse_logs"
KAFKA_GROUP = "clickhouse-logs-avro-new"

# `allow_experimental_reverse_key` is only recognised by ClickHouse 24.11+; omit it on older servers.
REVERSE_KEY_SETTING = lambda: "allow_experimental_reverse_key = 1,\n    " if clickhouse_supports_reverse_key() else ""


def LOGS34_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp),
    `original_expiry_timestamp` DateTime64(6),
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6) CODEC(DoubleDelta),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6) MATERIALIZED now(),
    `body` String,
    `severity_text` LowCardinality(String),
    `severity_number` Int32,
    `service_name` LowCardinality(String),
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes),
    `instrumentation_scope` String,
    `event_name` String,
    `attributes_map_str` Map(LowCardinality(String), String),
    `level` String ALIAS severity_text,
    `mat_body_ipv4_matches` Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1{0, 1}[0-9]){0, 1}[0-9])\\.){2, 2}([0-9]))'),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
    `_partition` UInt32,
    `_topic` String,
    `_offset` UInt64,
    `_bytes_uncompressed` UInt64,
    `_bytes_compressed` UInt64,
    `_record_count` UInt64,
    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
    INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            severity_text,
            resource_fingerprint
    )
)
ENGINE = {MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED)}
PARTITION BY toDate(original_expiry_timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
TTL original_expiry_timestamp
SETTINGS
    {REVERSE_KEY_SETTING()}index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    add_minmax_index_for_numeric_columns = 1,
    map_serialization_version = 'with_buckets'
"""


def LOGS_DISTRIBUTED_TABLE_SQL():
    return """
CREATE OR REPLACE TABLE {database}.logs_distributed AS {database}.{table_name} ENGINE = {engine}
""".format(
        engine=Distributed(
            data_table=TABLE_NAME,
            cluster=settings.CLICKHOUSE_LOGS_CLUSTER,
        ),
        database=settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        table_name=TABLE_NAME,
    )


def LOGS34_TO_LOG_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_log_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
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
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
        arrayJoin(attributes) AS attribute,
        'log' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attributes
)
"""


def LOGS34_TO_RESOURCE_ATTRIBUTES_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_resource_attributes TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
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
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        'resource' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        resource_attributes
)
"""


def LOGS34_TO_LOG_ATTRIBUTES3_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_log_attributes3 TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES3_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    original_expiry_time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    severity_text,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        severity_text AS severity_text,
        mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
        arrayJoin(attributes) AS attribute,
        'log' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        severity_text,
        attributes
)
"""


def LOGS34_TO_RESOURCE_ATTRIBUTES3_MV():
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}_to_resource_attributes3 TO {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{LOG_ATTRIBUTES3_TABLE_NAME}
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `original_expiry_time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `severity_text` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    original_expiry_time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    attribute_type,
    severity_text,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        severity_text AS severity_text,
        arrayJoin(resource_attributes) AS attribute,
        'resource' AS attribute_type,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{TABLE_NAME}
    GROUP BY
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        severity_text,
        resource_attributes
)
"""


def KAFKA_LOGS_AVRO_TABLE_SQL():
    return f"""
CREATE TABLE IF NOT EXISTS {settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE}.{KAFKA_TABLE_NAME}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `resource_attributes` Map(LowCardinality(String), String),
    `instrumentation_scope` String,
    `event_name` String,
    `attributes` Map(LowCardinality(String), String)
)
ENGINE = {kafka_engine(topic=KAFKA_TOPIC, group=KAFKA_GROUP, serialization="Avro", named_collection=KAFKA_NAMED_COLLECTION)}
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_num_consumers = 8,
    kafka_poll_timeout_ms = 3000,
    kafka_poll_max_batch_size = 1000,
    kafka_thread_per_consumer = 1
"""


def KAFKA_LOGS34_AVRO_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.kafka_logs34_avro_mv TO {db}.{TABLE_NAME}
(
    `uuid` String,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `instrumentation_scope` String,
    `event_name` String,
    `attributes_map_str` Map(String, String),
    `resource_attributes` Map(String, String),
    `team_id` Int32,
    `original_expiry_timestamp` DateTime64(6),
    `_partition` UInt64,
    `_topic` LowCardinality(String),
    `_offset` UInt64,
    `_record_count` Int64,
    `_bytes_uncompressed` Nullable(Int64),
    `_bytes_compressed` Nullable(Int64)
)
AS SELECT
    {KAFKA_TABLE_NAME}.* EXCEPT (created_at, attribute_values, attribute_keys, attributes, attributes_map_str, attributes_map_float, attributes_map_datetime, resource_attributes, bytes_uncompressed),
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    observed_timestamp + toIntervalDay(toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))) AS original_expiry_timestamp,
    _partition,
    _topic,
    _offset,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
    toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
    toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed
FROM {db}.{KAFKA_TABLE_NAME}
"""


def KAFKA_LOGS_AVRO_KAFKA_METRICS_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.kafka_logs_avro_kafka_metrics_mv TO {db}.logs_kafka_metrics
(
    `_partition` UInt32,
    `_topic` String,
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


def KAFKA_LOGS_AVRO_BILLING_METRICS_MV():
    db = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.kafka_logs_avro_billing_metrics_mv TO {db}.logs_billing_metrics
(
    `team_id` Int32,
    `time_bucket` DateTime,
    `service_name` LowCardinality(String),
    `bytes_uncompressed` SimpleAggregateFunction(sum, Float64),
    `bytes_compressed` SimpleAggregateFunction(sum, Float64),
    `record_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    service_name,
    sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
    sumSimpleState(_bytes_compressed) AS bytes_compressed,
    sumSimpleState(1) AS record_count
FROM
(
    SELECT
        team_id,
        toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
        service_name AS service_name,
        _bytes_uncompressed,
        _bytes_compressed
    FROM {db}.{TABLE_NAME}
)
GROUP BY team_id, time_bucket, service_name
"""
