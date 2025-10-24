-- temporary sql to initialise log tables for local development
-- will be removed once we have migrations set up
CREATE TABLE if not exists logs16
(
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `resource_attributes` Map(String, String),
    `resource_id` String,
    `instrumentation_scope` String,
    `event_name` String,
    `attributes` Map(String, String),
    `attributes_map_str` Map(String, String),
    `attributes_map_float` Map(String, Float64),
    `attributes_map_datetime` Map(String, DateTime64(6)),
    `attribute_keys` Array(String),
    `attribute_values` Array(String),
    `level` String ALIAS severity_text,
    INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
    INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_body_ngram body TYPE ngrambf_v1(3, 20000, 4, 0) GRANULARITY 1
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/logs16', '{replica}')
PARTITION BY toDate(timestamp)
ORDER BY (team_id, toStartOfMinute(timestamp) DESC, service_name, severity_text, toUnixTimestamp(timestamp) DESC, trace_id, span_id)
SETTINGS
allow_remote_fs_zero_copy_replication = 1,
allow_experimental_reverse_key = 1;

create or replace TABLE logs AS logs16 ENGINE = Distributed('posthog', 'default', 'logs16');

create table if not exists log_attributes

(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_count` SimpleAggregateFunction(sum, UInt64),
    INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
    INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/log_attributes', '{replica}')
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, service_name, time_bucket, attribute_key, attribute_value);

set enable_dynamic_type=1;
CREATE MATERIALIZED VIEW if not exists log_to_log_attributes TO log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_key` LowCardinality(String),
    `attribute_value` String,
    `attribute_count` SimpleAggregateFunction(sum, UInt64)
)
AS SELECT
    team_id,
    time_bucket,
    service_name,
    attribute_key,
    attribute_value,
    attribute_count
FROM (select
    team_id AS team_id,
    toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
    service_name AS service_name,
    arrayJoin(arrayMap((k, v) -> (k, if(length(v) > 256, '', v)), arrayFilter((k, v) -> (length(k) < 256), CAST(attributes, 'Array(Tuple(String, String))')))) AS attribute,
    attribute.1 AS attribute_key,
    CAST(JSONExtract(attribute.2, 'Dynamic'), 'String') AS attribute_value,
    sumSimpleState(1) AS attribute_count
FROM logs16
GROUP BY
    team_id,
    time_bucket,
    service_name,
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
    `created_at` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `resource_attributes` Map(String, String),
    `resource_id` String,
    `instrumentation_scope` String,
    `event_name` String,
    `attributes` Map(String, Nullable(String)),
    `attributes_map_str` Map(String, Nullable(String)),
    `attributes_map_float` Map(String, Nullable(Float64)),
    `attributes_map_datetime` Map(String, Nullable(DateTime64(6))),
    `attribute_keys` Array(Nullable(String)),
    `attribute_values` Array(Nullable(String))
)
ENGINE = Kafka('kafka:9092', 'clickhouse_logs', 'clickhouse-logs-avro', 'Avro')
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_security_protocol = 'PLAINTEXT',
    kafka_thread_per_consumer = 1,
    kafka_num_consumers = 1,
    kafka_poll_timeout_ms=15000,
    kafka_poll_max_batch_size=100,
    kafka_max_block_size=1000;

drop table if exists kafka_logs_avro_mv;

CREATE MATERIALIZED VIEW kafka_logs_avro_mv TO logs16
(
    `uuid` String,
    `team_id` Int32,
    `trace_id` String,
    `span_id` String,
    `trace_flags` Int32,
    `timestamp` DateTime64(6),
    `observed_timestamp` DateTime64(6),
    `created_at` DateTime64(6),
    `body` String,
    `severity_text` String,
    `severity_number` Int32,
    `service_name` String,
    `resource_attributes` Map(String, String),
    `resource_id` String,
    `instrumentation_scope` String,
    `event_name` String,
    `attributes` Map(String, Nullable(String)),
    `attributes_map_str` Map(String, Nullable(String)),
    `attributes_map_float` Map(String, Nullable(Float64)),
    `attributes_map_datetime` Map(String, Nullable(DateTime64(6))),
    `attribute_keys` Array(Nullable(String)),
    `attribute_values` Array(Nullable(String))
)
AS SELECT
*,
toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) as team_id
FROM kafka_logs_avro settings materialize_skip_indexes_on_insert = 1, distributed_background_insert_sleep_time_ms=5000, distributed_background_insert_batch=true;

select 'clickhouse logs tables initialised successfully!';
