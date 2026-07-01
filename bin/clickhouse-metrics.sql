-- temporary sql to initialise metrics tables for local development
-- will be removed once we have migrations set up
-- modelled after clickhouse-logs.sql following the same patterns
CREATE OR REPLACE TABLE metrics1
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `trace_flags` Int32 CODEC(ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `observed_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
    `service_name` LowCardinality(String) CODEC(ZSTD(1)),
    `metric_name` LowCardinality(String) CODEC(ZSTD(1)),
    `metric_type` LowCardinality(String) CODEC(ZSTD(1)),
    `value` Float64 CODEC(Gorilla, ZSTD(1)),
    `count` UInt64 DEFAULT 1 CODEC(T64, ZSTD(1)),
    `histogram_bounds` Array(Float64) CODEC(ZSTD(1)),
    `histogram_counts` Array(UInt64) CODEC(ZSTD(1)),
    `unit` LowCardinality(String) CODEC(ZSTD(1)),
    `aggregation_temporality` LowCardinality(String) CODEC(ZSTD(1)),
    `is_monotonic` Bool DEFAULT false CODEC(ZSTD(1)),
    `resource_attributes` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `attributes_map_float` Map(LowCardinality(String), Float64) CODEC(ZSTD(1)),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    INDEX idx_metric_name_set metric_name TYPE set(100) GRANULARITY 1,
    INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint,
            count() AS event_count,
            sum(value) AS total_value,
            min(value) AS min_value,
            max(value) AS max_value
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            metric_name,
            metric_type,
            resource_fingerprint
    )
)
ENGINE = MergeTree
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
ORDER BY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1;

create or replace TABLE metrics AS metrics1 ENGINE = Distributed('posthog', 'default', 'metrics1');

-- Raw metrics as a TSDB series/samples split (NOT the fat one-row-per-event
-- shape logs/traces use). Mirrors posthog/clickhouse/metrics/metric_events.py
-- (Replicated in prod). metric_series stores each label set ONCE; metric_samples
-- is tiny (fingerprint + timestamp + value + trace_id), joined on
-- series_fingerprint at query time.
CREATE OR REPLACE TABLE metric_series1
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(DoubleDelta),
    `metric_type` LowCardinality(String),
    `unit` LowCardinality(String),
    `service_name` LowCardinality(String),
    `resource_attributes` Map(LowCardinality(String), String),
    `attributes` Map(LowCardinality(String), String),
    `last_seen` DateTime64(6) CODEC(DoubleDelta),
    INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
    INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (team_id, metric_name, series_fingerprint)
SETTINGS index_granularity = 8192;

create or replace TABLE metric_series AS metric_series1 ENGINE = Distributed('posthog', 'default', 'metric_series1');

CREATE OR REPLACE TABLE metric_samples1
(
    `team_id` Int32,
    `metric_name` LowCardinality(String),
    `series_fingerprint` UInt64 CODEC(DoubleDelta),
    `timestamp` DateTime64(6) CODEC(DoubleDelta),
    `value` Float64 CODEC(Gorilla),
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = MergeTree
PARTITION BY toDate(timestamp)
ORDER BY (team_id, metric_name, series_fingerprint, timestamp)
TTL toDateTime(timestamp) + INTERVAL 30 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;

create or replace TABLE metric_samples AS metric_samples1 ENGINE = Distributed('posthog', 'default', 'metric_samples1');

-- Attribute discovery table (reuses logs pattern)
create or replace table default.metric_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_fingerprint` UInt64 DEFAULT 0,
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_type` LowCardinality(String),
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = AggregatingMergeTree
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value);

-- MV: resource attributes -> metric_attributes
drop view if exists metric_to_resource_attributes;
CREATE MATERIALIZED VIEW metric_to_resource_attributes TO metric_attributes
(
    `team_id` Int32,
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
    time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    'resource' as attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(resource_attributes) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM metrics1
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

-- MV: metric attributes -> metric_attributes
drop view if exists metric_to_metric_attributes;
CREATE MATERIALIZED VIEW metric_to_metric_attributes TO metric_attributes
(
    `team_id` Int32,
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
    time_bucket,
    service_name,
    resource_fingerprint,
    attribute_key,
    attribute_value,
    'metric' as attribute_type,
    attribute_count
FROM
(
    SELECT
        team_id AS team_id,
        toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
        service_name AS service_name,
        resource_fingerprint,
        arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
        attribute.1 AS attribute_key,
        attribute.2 AS attribute_value,
        sumSimpleState(1) AS attribute_count
    FROM metrics1
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

-- Kafka engine table reading AVRO from clickhouse_metrics topic
CREATE OR REPLACE TABLE kafka_metrics_avro
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
ENGINE = Kafka('kafka:9092', 'clickhouse_metrics', 'clickhouse-metrics-avro', 'Avro')
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_security_protocol = 'PLAINTEXT',
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 1,
    kafka_poll_timeout_ms=15000,
    kafka_poll_max_batch_size=10,
    kafka_max_block_size=10;

-- MV: kafka_metrics_avro -> metrics1
drop table if exists kafka_metrics_avro_mv;

CREATE MATERIALIZED VIEW kafka_metrics_avro_mv TO metrics1
AS SELECT
    uuid,
    trace_id,
    span_id,
    ifNull(trace_flags, 0) as trace_flags,
    timestamp,
    observed_timestamp,
    ifNull(service_name, '') as service_name,
    ifNull(metric_name, '') as metric_name,
    ifNull(metric_type, '') as metric_type,
    ifNull(value, 0) as value,
    toUInt64(ifNull(count, 1)) as count,
    histogram_bounds,
    arrayMap(x -> toUInt64(x), histogram_counts) as histogram_counts,
    ifNull(unit, '') as unit,
    ifNull(aggregation_temporality, '') as aggregation_temporality,
    ifNull(is_monotonic, 0) as is_monotonic,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    ifNull(instrumentation_scope, '') as instrumentation_scope,
    mapSort(mapApply((k,v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) as attributes_map_str,
    mapSort(mapFilter((k, v) -> isNotNull(v), mapApply((k,v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))), attributes))) as attributes_map_float,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id
FROM kafka_metrics_avro settings min_insert_block_size_rows=0, min_insert_block_size_bytes=0;

-- Two MVs on the existing kafka_metrics_avro: every clickhouse_metrics point fans
-- into metric_series (labels, deduped) and metric_samples (the tiny row), alongside
-- kafka_metrics_avro_mv -> metrics1. series_fingerprint is assigned ONCE at ingest
-- (capture-logs) and shipped in the Avro payload; both MVs read it verbatim — they do
-- NOT recompute it. ClickHouse never computes the identity (no cityHash64 over the
-- maps), so the two tables cannot disagree and the hash cannot collapse. The Avro
-- `long` carries the u64 bits as signed; reinterpretAsUInt64 restores them.
-- Rows with a NULL series_fingerprint (a producer that predates the ingest change, or
-- a rollback) are dropped, not coerced to 0: coalescing to a shared id would collapse
-- every such series onto one ReplacingMergeTree row with arbitrary labels — silent join
-- corruption. Dropped rows are recoverable by replaying the topic once ingest is live.
drop table if exists kafka_metrics_avro_to_metric_series;
CREATE MATERIALIZED VIEW kafka_metrics_avro_to_metric_series TO metric_series1
AS SELECT
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id,
    ifNull(metric_name, '') as metric_name,
    reinterpretAsUInt64(assumeNotNull(series_fingerprint)) as series_fingerprint,
    ifNull(metric_type, '') as metric_type,
    ifNull(unit, '') as unit,
    ifNull(service_name, '') as service_name,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)) AS attributes,
    timestamp as last_seen
FROM kafka_metrics_avro
WHERE series_fingerprint IS NOT NULL
settings min_insert_block_size_rows=0, min_insert_block_size_bytes=0;

drop table if exists kafka_metrics_avro_to_metric_samples;
CREATE MATERIALIZED VIEW kafka_metrics_avro_to_metric_samples TO metric_samples1
AS SELECT
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id,
    ifNull(metric_name, '') as metric_name,
    reinterpretAsUInt64(assumeNotNull(series_fingerprint)) as series_fingerprint,
    timestamp,
    ifNull(value, 0) as value,
    trace_id,
    span_id,
    ifNull(trace_flags, 0) as trace_flags
FROM kafka_metrics_avro
WHERE series_fingerprint IS NOT NULL
settings min_insert_block_size_rows=0, min_insert_block_size_bytes=0;

-- Kafka consumer lag tracking
create or replace table metrics_kafka_metrics
(
    `_partition` UInt32,
    `_topic` String,
    `max_offset` SimpleAggregateFunction(max, UInt64),
    `max_observed_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_timestamp` SimpleAggregateFunction(max, DateTime64(9)),
    `max_created_at` SimpleAggregateFunction(max, DateTime64(9)),
    `max_lag` SimpleAggregateFunction(max, UInt64)
)
ENGINE = MergeTree
ORDER BY (_topic, _partition);

drop view if exists kafka_metrics_avro_kafka_metrics_mv;
CREATE MATERIALIZED VIEW kafka_metrics_avro_kafka_metrics_mv TO metrics_kafka_metrics
AS
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) as max_offset,
        maxSimpleState(observed_timestamp) as max_observed_timestamp,
        maxSimpleState(timestamp) as max_timestamp,
        maxSimpleState(now()) as max_created_at,
        maxSimpleState(now() - observed_timestamp) as max_lag
    FROM kafka_metrics_avro
    group by _partition, _topic;

-- Read aliases in the `posthog` database.
-- The product connection uses CLICKHOUSE_DATABASE=posthog and resolves the
-- bare names `metrics`, `metric_attributes`, `metrics_kafka_metrics` there,
-- while everything above lives in `default` (this script runs unqualified
-- through docker clickhouse-client). Without these aliases the product reads
-- empty same-named tables in `posthog` while data accumulates in `default`.
DROP TABLE IF EXISTS posthog.metrics1_to_metric_attributes;
DROP TABLE IF EXISTS posthog.metrics1_to_resource_attributes;
DROP TABLE IF EXISTS posthog.metrics1;
CREATE OR REPLACE TABLE posthog.metrics AS default.metrics1 ENGINE = Distributed('posthog', 'default', 'metrics1');
DROP TABLE IF EXISTS posthog.metric_attributes;
CREATE TABLE posthog.metric_attributes AS default.metric_attributes ENGINE = Distributed('posthog', 'default', 'metric_attributes');
DROP TABLE IF EXISTS posthog.metrics_kafka_metrics;
CREATE TABLE posthog.metrics_kafka_metrics AS default.metrics_kafka_metrics ENGINE = Distributed('posthog', 'default', 'metrics_kafka_metrics');
DROP TABLE IF EXISTS posthog.metric_series;
CREATE OR REPLACE TABLE posthog.metric_series AS default.metric_series1 ENGINE = Distributed('posthog', 'default', 'metric_series1');
DROP TABLE IF EXISTS posthog.metric_samples;
CREATE OR REPLACE TABLE posthog.metric_samples AS default.metric_samples1 ENGINE = Distributed('posthog', 'default', 'metric_samples1');

select 'clickhouse metrics tables initialised successfully!';
