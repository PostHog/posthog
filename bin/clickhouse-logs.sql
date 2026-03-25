-- temporary sql to initialise log tables for local development
-- will be removed once we have migrations set up
CREATE OR REPLACE FUNCTION extractIPv4Substrings AS
(
  body -> extractAll(body, '(\d\.((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){2,2}([0-9]))')
);
CREATE OR REPLACE TABLE logs31
(
    -- time bucket is set to day which means it's effectively not in the order by key (same as partition)
    -- but gives us flexibility to add the bucket to the order key if needed
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `trace_flags` Int32 CODEC(ZSTD(1)),
    `timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `observed_timestamp` DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
    `created_at` DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
    `body` String CODEC(ZSTD(1)),
    `severity_text` String CODEC(ZSTD(1)),
    `severity_number` Int32 CODEC(ZSTD(1)),
    `service_name` String CODEC(ZSTD(1)),
    `resource_attributes` Map(String, String) CODEC(ZSTD(1)),
    `resource_fingerprint` UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
    `resource_id` String CODEC(ZSTD(1)),
    `instrumentation_scope` String CODEC(ZSTD(1)),
    `event_name` String CODEC(ZSTD(1)),
    `attributes_map_str` Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    `attributes_map_float` Map(LowCardinality(String), Float64) CODEC(ZSTD(1)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64(6)) CODEC(ZSTD(1)),
    `level` String ALIAS severity_text,
    `mat_body_ipv4_matches` Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\\.){2,2}([0-9]))'),
    `time_minute` DateTime ALIAS toStartOfMinute(timestamp),
    `attributes` Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram3 body TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
    INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
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
ENGINE = MergeTree
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    allow_part_offset_column_in_projections = 1;

create or replace TABLE logs AS logs31 ENGINE = Distributed('posthog', 'default', 'logs31');

create or replace table default.log_attributes

(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `resource_id` String DEFAULT '',
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

drop view if exists log_to_resource_attributes;
CREATE MATERIALIZED VIEW log_to_resource_attributes TO log_attributes
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
    FROM logs31
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

drop view if exists log_to_log_attributes;
CREATE MATERIALIZED VIEW log_to_log_attributes TO log_attributes
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
    'log' as attribute_type,
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
    FROM logs31
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

CREATE OR REPLACE TABLE kafka_logs_avro
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
ENGINE = Kafka('kafka:9092', 'clickhouse_logs', 'clickhouse-logs-avro', 'Avro')
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_security_protocol = 'PLAINTEXT',
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 1,
    kafka_poll_timeout_ms=15000,
    kafka_poll_max_batch_size=10,
    kafka_max_block_size=10;

drop table if exists kafka_logs_avro_mv;

CREATE MATERIALIZED VIEW kafka_logs_avro_mv TO logs31
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
AS SELECT
* except (attributes, resource_attributes),
mapSort(mapApply((k,v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) as attributes_map_str,
mapSort(mapFilter((k, v) -> isNotNull(v), mapApply((k,v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))), attributes))) as attributes_map_float,
mapSort(mapFilter((k, v) -> isNotNull(v), mapApply((k,v) -> (concat(k, '__datetime'), parseDateTimeBestEffortOrNull(JSONExtract(v, 'String'), 6)), attributes))) as attributes_map_datetime,
mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id
FROM kafka_logs_avro settings min_insert_block_size_rows=0, min_insert_block_size_bytes=0;

create or replace table logs_kafka_metrics
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

drop view if exists kafka_logs_avro_kafka_metrics_mv;
CREATE MATERIALIZED VIEW kafka_logs_avro_kafka_metrics_mv TO logs_kafka_metrics
AS
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) as max_offset,
        maxSimpleState(observed_timestamp) as max_observed_timestamp,
        maxSimpleState(timestamp) as max_timestamp,
        maxSimpleState(now()) as max_created_at,
        maxSimpleState(now() - observed_timestamp) as max_lag
    FROM kafka_logs_avro
    group by _partition, _topic;

-- spans tables
CREATE OR REPLACE TABLE trace_spans
(
    `time_bucket` DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
    `uuid` String CODEC(ZSTD(1)),
    `team_id` Int32 CODEC(ZSTD(1)),
    `trace_id` String CODEC(ZSTD(1)),
    `span_id` String CODEC(ZSTD(1)),
    `parent_span_id` String CODEC(ZSTD(1)),
    `is_root_span` Bool MATERIALIZED (replaceAll(trimRight(parent_span_id, '='), 'A', '')) = '' CODEC(DoubleDelta, ZSTD(1)),
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

    PROJECTION projection_aggregate_counts
    (
        SELECT
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            resource_fingerprint,
            count() AS event_count
        GROUP BY
            team_id,
            time_bucket,
            toStartOfMinute(timestamp),
            service_name,
            resource_fingerprint
    ),

    PROJECTION projection_index_trace_id
    (
        SELECT _part_offset
        ORDER BY trace_id
    ),

    PROJECTION projection_index_span_id
    (
        SELECT _part_offset
        ORDER BY span_id
    ),

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
ENGINE = MergeTree
PARTITION BY toDate(timestamp)
PRIMARY KEY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)
SETTINGS
    index_granularity_bytes = 104857600,
    index_granularity = 8192,
    ttl_only_drop_parts = 1,
    allow_part_offset_column_in_projections = 1;

CREATE OR REPLACE TABLE trace_spans_distributed AS trace_spans ENGINE = Distributed('posthog', 'default', 'trace_spans');

CREATE OR REPLACE TABLE trace_attributes
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

drop view if exists trace_span_to_resource_attributes;
CREATE MATERIALIZED VIEW trace_span_to_resource_attributes TO trace_attributes
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
    FROM trace_spans
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

drop view if exists trace_span_to_trace_attributes;
CREATE MATERIALIZED VIEW trace_span_to_trace_attributes TO trace_attributes
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
    'span' as attribute_type,
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
    FROM trace_spans
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute
);

drop table if exists kafka_spans_avro;
CREATE OR REPLACE TABLE kafka_trace_spans_avro
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
ENGINE = Kafka('kafka:9092', 'clickhouse_traces', 'clickhouse-spans-avro', 'Avro')
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_security_protocol = 'PLAINTEXT',
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 1,
    kafka_poll_timeout_ms=15000,
    kafka_poll_max_batch_size=10,
    kafka_max_block_size=10;

drop table if exists kafka_spans_avro_mv;
drop table if exists kafka_trace_spans_avro_mv;

CREATE MATERIALIZED VIEW kafka_trace_spans_avro_mv TO trace_spans
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
    `team_id` Int32
)
AS SELECT
* except (attributes, resource_attributes, kind, flags, dropped_attributes_count, dropped_events_count, dropped_links_count, status_code),
toInt8(kind) as kind,
toUInt32(flags) as flags,
toUInt32(dropped_attributes_count) as dropped_attributes_count,
toUInt32(dropped_events_count) as dropped_events_count,
toUInt32(dropped_links_count) as dropped_links_count,
toInt16(status_code) as status_code,
mapSort(mapApply((k,v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) as attributes_map_str,
mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id
FROM kafka_trace_spans_avro SETTINGS min_insert_block_size_rows=0, min_insert_block_size_bytes=0;

CREATE OR REPLACE TABLE trace_spans_kafka_metrics
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

drop view if exists kafka_trace_spans_avro_kafka_metrics_mv;
CREATE MATERIALIZED VIEW kafka_trace_spans_avro_kafka_metrics_mv TO trace_spans_kafka_metrics
AS
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) as max_offset,
        maxSimpleState(observed_timestamp) as max_observed_timestamp,
        maxSimpleState(timestamp) as max_timestamp,
        maxSimpleState(now()) as max_created_at,
        maxSimpleState(now() - observed_timestamp) as max_lag
    FROM kafka_trace_spans_avro
    group by _partition, _topic;

select 'clickhouse logs tables initialised successfully!';
