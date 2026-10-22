-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the prod-eu/logs node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.kafka_trace_spans_avro (
  uuid String,
  trace_id String,
  span_id String,
  parent_span_id String,
  trace_state String,
  name String,
  kind Int32,
  flags Int32,
  timestamp DateTime64(6),
  end_time DateTime64(6),
  observed_timestamp DateTime64(6),
  service_name String,
  resource_attributes Map(LowCardinality(String), String),
  instrumentation_scope String,
  attributes Map(LowCardinality(String), String),
  dropped_attributes_count Int32,
  events Array(String),
  dropped_events_count Int32,
  links Array(String),
  dropped_links_count Int32,
  status_code Int32,
  retention_days Nullable(Int32)
) ENGINE = Kafka(warpstream_traces) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-traces-avro', kafka_num_consumers = 2, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_traces';
CREATE TABLE posthog.log_attributes2 (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String CODEC(ZSTD(5)),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String) DEFAULT 'log',
  original_expiry_time_bucket DateTime DEFAULT now(),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/log_attributes34', '{replica}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(time_bucket) TTL time_bucket + toIntervalDay(15) SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.log_attributes3 (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String CODEC(ZSTD(5)),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String) DEFAULT 'log',
  original_expiry_time_bucket DateTime DEFAULT now(),
  severity_text LowCardinality(String),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes3', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.log_attributes_distributed (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String CODEC(ZSTD(5)),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String) DEFAULT 'log',
  original_expiry_time_bucket DateTime DEFAULT now(),
  severity_text LowCardinality(String)
) ENGINE = Distributed('logs', 'posthog', 'log_attributes3');
CREATE TABLE posthog.logs34 (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp),
  original_expiry_timestamp DateTime64(6),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  trace_flags Int32,
  timestamp DateTime64(6) CODEC(DoubleDelta),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  body String,
  severity_text LowCardinality(String),
  severity_number Int32,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  event_name String,
  attributes_map_str Map(LowCardinality(String), String),
  level String ALIAS severity_text,
  mat_body_ipv4_matches Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\.)(2, 2)([0-9]))'),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
  _partition UInt32,
  _topic String,
  _offset UInt64,
  _bytes_uncompressed UInt64,
  _bytes_compressed UInt64,
  _record_count UInt64,
  pattern String,
  pattern_version UInt8,
  INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
  INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
  INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
  INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
  INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
  PROJECTION projection_aggregate_counts (SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  severity_text,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.logs34', '{replica}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', storage_policy = 's3_tiered', ttl_only_drop_parts = 1;
CREATE TABLE posthog.logs_billing_metrics (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  bytes_uncompressed SimpleAggregateFunction(sum, UInt64),
  bytes_compressed SimpleAggregateFunction(sum, UInt64),
  record_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/logs_billing_metrics', '{replica}') ORDER BY (team_id, time_bucket, service_name) PARTITION BY toYYYYMM(time_bucket) SETTINGS deduplicate_merge_projection_mode = 'rebuild', index_granularity = 8192;
CREATE TABLE posthog.logs_billing_metrics_distributed (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  bytes_uncompressed SimpleAggregateFunction(sum, UInt64),
  bytes_compressed SimpleAggregateFunction(sum, UInt64),
  record_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'logs_billing_metrics');
CREATE TABLE posthog.logs_distributed (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp),
  original_expiry_timestamp DateTime64(6),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  trace_flags Int32,
  timestamp DateTime64(6) CODEC(DoubleDelta),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  body String,
  severity_text LowCardinality(String),
  severity_number Int32,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  event_name String,
  attributes_map_str Map(LowCardinality(String), String),
  level String ALIAS severity_text,
  mat_body_ipv4_matches Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\.)(2, 2)([0-9]))'),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
  _partition UInt32,
  _topic String,
  _offset UInt64,
  _bytes_uncompressed UInt64,
  _bytes_compressed UInt64,
  _record_count UInt64,
  pattern String,
  pattern_version UInt8
) ENGINE = Distributed('logs', 'posthog', 'logs34');
CREATE TABLE posthog.logs_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/logs_kafka_metrics', '{replica}') ORDER BY (_topic, _partition) SETTINGS deduplicate_merge_projection_mode = 'rebuild', index_granularity = 8192;
CREATE TABLE posthog.logs_kafka_metrics_distributed (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'logs_kafka_metrics');
CREATE TABLE posthog.logs_pattern_buckets (
  team_id Int32,
  time_bucket DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
  service_name LowCardinality(String),
  namespace LowCardinality(String),
  environment LowCardinality(String),
  severity_text LowCardinality(String),
  pattern_version UInt8,
  pattern String,
  retention_days SimpleAggregateFunction(max, UInt16),
  log_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_pattern_buckets', '{replica}-{shard}') PRIMARY KEY (team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version) ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version, pattern) PARTITION BY toDate(time_bucket) TTL time_bucket + toIntervalDay(greatest(42, retention_days)) SETTINGS index_granularity = 8192, ttl_only_drop_parts = 0;
CREATE TABLE posthog.logs_pattern_buckets_distributed (
  team_id Int32,
  time_bucket DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
  service_name LowCardinality(String),
  namespace LowCardinality(String),
  environment LowCardinality(String),
  severity_text LowCardinality(String),
  pattern_version UInt8,
  pattern String,
  retention_days SimpleAggregateFunction(max, UInt16),
  log_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'logs_pattern_buckets');
CREATE TABLE posthog.logs_volume_buckets (
  team_id Int32,
  time_bucket DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
  service_name LowCardinality(String),
  namespace LowCardinality(String),
  environment LowCardinality(String),
  severity_text LowCardinality(String),
  retention_days SimpleAggregateFunction(max, UInt16),
  log_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_volume_buckets', '{replica}-{shard}') ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text) PARTITION BY toDate(time_bucket) TTL time_bucket + toIntervalDay(greatest(42, retention_days)) SETTINGS index_granularity = 8192, ttl_only_drop_parts = 0;
CREATE TABLE posthog.logs_volume_buckets_distributed (
  team_id Int32,
  time_bucket DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
  service_name LowCardinality(String),
  namespace LowCardinality(String),
  environment LowCardinality(String),
  severity_text LowCardinality(String),
  retention_days SimpleAggregateFunction(max, UInt16),
  log_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'logs_volume_buckets');
CREATE TABLE posthog.metric_attributes (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metric_attributes', '{replica}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(time_bucket) SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192;
CREATE TABLE posthog.metric_attributes2 (
  team_id Int32,
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_attributes2', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, attribute_key, attribute_value) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metric_attributes3 (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_attributes3', '{replica}-{shard}') ORDER BY (team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metric_attributes_distributed (
  team_id Int32,
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'metric_attributes2');
CREATE TABLE posthog.metric_names3 (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6))
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_names3', '{replica}-{shard}') ORDER BY (team_id, time_bucket, metric_name, original_expiry_time_bucket) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_timestamp SETTINGS index_granularity = 8192;
CREATE TABLE posthog.metric_samples1 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  timestamp DateTime64(6) CODEC(DoubleDelta),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1,
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  trace_id String,
  span_id String,
  trace_flags Int32,
  INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metric_samples1', '{replica}-{shard}') ORDER BY (team_id, metric_name, series_fingerprint, timestamp) PARTITION BY toDate(timestamp) TTL toDateTime(timestamp) + toIntervalDay(30) SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metric_series1 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6) CODEC(DoubleDelta),
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series1', '{replica}-{shard}', last_seen) ORDER BY (team_id, metric_name, series_fingerprint) TTL toDateTime(last_seen) + toIntervalDay(90) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.metric_series2 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6),
  original_expiry_timestamp DateTime64(6),
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_last_seen_minmax last_seen TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series2', '{replica}-{shard}', last_seen) ORDER BY (team_id, metric_name, series_fingerprint) TTL original_expiry_timestamp SETTINGS index_granularity = 8192;
CREATE TABLE posthog.metric_series3 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6),
  original_expiry_timestamp DateTime64(6),
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_last_seen_minmax last_seen TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series3', '{replica}-{shard}', last_seen) ORDER BY (team_id, metric_name, series_fingerprint) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS index_granularity = 8192;
CREATE TABLE posthog.metric_series_distributed (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6),
  original_expiry_timestamp DateTime64(6)
) ENGINE = Distributed('logs', 'posthog', 'metric_series2');
CREATE TABLE posthog.metrics1 (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  trace_flags Int32,
  timestamp DateTime64(6),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  service_name LowCardinality(String),
  metric_name LowCardinality(String),
  metric_type LowCardinality(String),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1 CODEC(T64),
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  attributes_map_str Map(LowCardinality(String), String),
  attributes_map_float Map(LowCardinality(String), Float64),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  INDEX idx_metric_name_set metric_name TYPE set(100) GRANULARITY 1,
  INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
  INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
  PROJECTION projection_aggregate_counts (SELECT
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
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics1', '{replica}') ORDER BY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp) PARTITION BY toDate(timestamp) SETTINGS index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metrics2 (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime MATERIALIZED toStartOfHour(timestamp),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  resource_fingerprint UInt64 DEFAULT 0,
  timestamp DateTime64(6) CODEC(DoubleDelta),
  observed_timestamp DateTime64(6),
  original_expiry_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  service_name LowCardinality(String),
  metric_type LowCardinality(String),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1 CODEC(T64),
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  trace_id String,
  span_id String,
  trace_flags Int32,
  has_labels Bool DEFAULT false,
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  instrumentation_scope String,
  _partition UInt32,
  _topic String,
  _offset UInt64,
  INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_trace_id_bf trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
  INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
  PROJECTION projection_series_activity (SELECT
  team_id,
  service_name,
  metric_name,
  metric_type,
  resource_fingerprint,
  series_fingerprint,
  toStartOfHour(timestamp) AS hour,
  count() AS sample_count,
  max(timestamp) AS last_seen
GROUP BY
  team_id, service_name, metric_name, metric_type, resource_fingerprint, series_fingerprint, hour)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metrics2', '{replica}-{shard}') ORDER BY (team_id, metric_name, time_bucket, series_fingerprint, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metrics4_attributes (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_time_bucket_minmax time_bucket TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_attributes', '{replica}-{shard}') ORDER BY (team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metrics4_names (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6)),
  service_name LowCardinality(String),
  metric_types SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  metric_type String ALIAS metric_types[1]
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_names', '{replica}-{shard}') ORDER BY (team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_timestamp SETTINGS index_granularity = 8192;
CREATE TABLE posthog.metrics4_samples (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime,
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  original_expiry_date Date32,
  resource_fingerprint SimpleAggregateFunction(any, UInt64),
  service_name SimpleAggregateFunction(any, LowCardinality(String)),
  metric_type SimpleAggregateFunction(any, LowCardinality(String)),
  unit SimpleAggregateFunction(any, LowCardinality(String)),
  aggregation_temporality SimpleAggregateFunction(any, LowCardinality(String)),
  is_monotonic SimpleAggregateFunction(max, UInt8),
  has_labels SimpleAggregateFunction(max, UInt8),
  instrumentation_scope SimpleAggregateFunction(any, String),
  histogram_bounds SimpleAggregateFunction(anyLast, Array(Float64)),
  _topic SimpleAggregateFunction(any, LowCardinality(String)),
  timestamp_arr SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6))) CODEC(DoubleDelta, Default),
  observed_timestamp_arr SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6))) CODEC(DoubleDelta, Default),
  value_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Float64)) CODEC(Gorilla(8), Default),
  count_arr SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64)) CODEC(T64, Default),
  histogram_counts_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64))) CODEC(T64, Default),
  trace_id_arr SimpleAggregateFunction(groupArrayArray(10000), Array(String)),
  span_id_arr SimpleAggregateFunction(groupArrayArray(10000), Array(String)),
  trace_flags_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Int32)),
  timestamp_min DateTime64(6) ALIAS arrayMin(timestamp_arr),
  timestamp_max DateTime64(6) ALIAS arrayMax(timestamp_arr),
  INDEX idx_metric_type_set metric_type TYPE set(10) GRANULARITY 1,
  INDEX idx_time_bucket_minmax time_bucket TYPE minmax GRANULARITY 1,
  INDEX idx_trace_id_bf trace_id_arr TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_timestamp_min_minmax timestamp_min TYPE minmax GRANULARITY 1,
  INDEX idx_timestamp_max_minmax timestamp_max TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_samples', '{replica}-{shard}') ORDER BY (team_id, metric_name, time_bucket, series_fingerprint) PARTITION BY original_expiry_date TTL original_expiry_date SETTINGS index_granularity = 128, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metrics4_series (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  attributes Map(LowCardinality(String), String),
  timestamp DateTime64(6),
  time_bucket DateTime MATERIALIZED toStartOfHour(timestamp),
  original_expiry_timestamp DateTime64(6),
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_resource_fingerprint resource_fingerprint TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1,
  INDEX idx_time_bucket_minmax time_bucket TYPE minmax GRANULARITY 1,
  PROJECTION services_by_hour (SELECT
  team_id,
  time_bucket,
  service_name,
  uniqExact(metric_name),
  uniq(series_fingerprint),
  max(timestamp)
GROUP BY
  team_id, time_bucket, service_name)
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_series', '{replica}-{shard}', timestamp) ORDER BY (team_id, metric_name, series_fingerprint, time_bucket) PARTITION BY toStartOfWeek(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS deduplicate_merge_projection_mode = 'rebuild', index_granularity = 1024, ttl_only_drop_parts = 1;
CREATE TABLE posthog.metrics_distributed (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime MATERIALIZED toStartOfHour(timestamp),
  series_fingerprint UInt64 CODEC(Delta(8), Default),
  resource_fingerprint UInt64 DEFAULT 0,
  timestamp DateTime64(6) CODEC(DoubleDelta),
  observed_timestamp DateTime64(6),
  original_expiry_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  service_name LowCardinality(String),
  metric_type LowCardinality(String),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1 CODEC(T64),
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  trace_id String,
  span_id String,
  trace_flags Int32,
  has_labels Bool DEFAULT false,
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  instrumentation_scope String,
  _partition UInt32,
  _topic String,
  _offset UInt64
) ENGINE = Distributed('logs', 'posthog', 'metrics2');
CREATE TABLE posthog.metrics_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics_kafka_metrics', '{replica}') ORDER BY (_topic, _partition) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.query_log_archive (
  initial_query_start_time DateTime64(6, 'UTC'),
  team_id Int64,
  initial_query_id String,
  is_initial_query SimpleAggregateFunction(max, UInt8),
  hostname SimpleAggregateFunction(max, LowCardinality(String)),
  user SimpleAggregateFunction(max, LowCardinality(String)),
  type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)),
  event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  query_duration_ms SimpleAggregateFunction(max, UInt64),
  read_rows SimpleAggregateFunction(sum, UInt64),
  read_bytes SimpleAggregateFunction(sum, UInt64),
  written_rows SimpleAggregateFunction(sum, UInt64),
  written_bytes SimpleAggregateFunction(sum, UInt64),
  result_rows SimpleAggregateFunction(sum, UInt64),
  result_bytes SimpleAggregateFunction(sum, UInt64),
  memory_usage SimpleAggregateFunction(max, UInt64),
  memory_usage_sum SimpleAggregateFunction(sum, UInt64),
  peak_threads_usage SimpleAggregateFunction(sum, UInt64),
  execution_count SimpleAggregateFunction(sum, UInt64),
  current_database SimpleAggregateFunction(max, LowCardinality(String)),
  query SimpleAggregateFunction(max, String),
  normalized_query_hash SimpleAggregateFunction(max, UInt64),
  query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)),
  tables SimpleAggregateFunction(max, Array(String)),
  exception_code SimpleAggregateFunction(max, Int32),
  exception SimpleAggregateFunction(max, String),
  stack_trace SimpleAggregateFunction(max, String),
  ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  lc_org_id SimpleAggregateFunction(max, String),
  lc_user_id SimpleAggregateFunction(max, Int64),
  lc_session_id SimpleAggregateFunction(max, String),
  lc_is_impersonated SimpleAggregateFunction(max, Bool),
  lc_workflow SimpleAggregateFunction(max, LowCardinality(String)),
  lc_kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_id SimpleAggregateFunction(max, String),
  lc_route_id SimpleAggregateFunction(max, String),
  lc_access_method SimpleAggregateFunction(max, LowCardinality(String)),
  lc_api_key_label SimpleAggregateFunction(max, String),
  lc_api_key_mask SimpleAggregateFunction(max, String),
  lc_query_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_product SimpleAggregateFunction(max, LowCardinality(String)),
  lc_chargeable SimpleAggregateFunction(max, Bool),
  lc_name SimpleAggregateFunction(max, String),
  lc_request_name SimpleAggregateFunction(max, String),
  lc_client_query_id SimpleAggregateFunction(max, String),
  lc_dashboard_id SimpleAggregateFunction(max, Int64),
  lc_insight_id SimpleAggregateFunction(max, Int64),
  lc_cohort_id SimpleAggregateFunction(max, Int64),
  lc_batch_export_id SimpleAggregateFunction(max, String),
  lc_experiment_id SimpleAggregateFunction(max, Int64),
  lc_experiment_feature_flag_key SimpleAggregateFunction(max, String),
  lc_alert_config_id SimpleAggregateFunction(max, String),
  lc_feature SimpleAggregateFunction(max, LowCardinality(String)),
  lc_table_id SimpleAggregateFunction(max, String),
  lc_warehouse_query SimpleAggregateFunction(max, Bool),
  lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)),
  lc_service_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_workload SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__query SimpleAggregateFunction(max, String),
  lc_query SimpleAggregateFunction(max, String),
  lc_modifiers SimpleAggregateFunction(max, String),
  lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_id SimpleAggregateFunction(max, String),
  lc_temporal__workflow_run_id SimpleAggregateFunction(max, String),
  lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__activity_id SimpleAggregateFunction(max, String),
  lc_temporal__attempt SimpleAggregateFunction(max, Int64),
  lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_dagster__run_id SimpleAggregateFunction(max, String),
  lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_name SimpleAggregateFunction(max, String),
  lc_experiment_metric_name SimpleAggregateFunction(max, String),
  lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_precompute_table SimpleAggregateFunction(max, String),
  lc_experiment_query_group_id SimpleAggregateFunction(max, String),
  lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_scan_date_from SimpleAggregateFunction(max, String),
  lc_experiment_scan_date_to SimpleAggregateFunction(max, String),
  lc_precompute_window_start SimpleAggregateFunction(max, String),
  lc_precompute_window_end SimpleAggregateFunction(max, String),
  lc_plan_fingerprint SimpleAggregateFunction(max, String),
  lc_estimated_rows SimpleAggregateFunction(max, Int64),
  lc_estimated_bytes SimpleAggregateFunction(max, Int64),
  query_id String,
  event_time DateTime('UTC'),
  event_date Date,
  query_start_time DateTime('UTC'),
  query_start_time_microseconds DateTime64(6, 'UTC'),
  query_kind LowCardinality(String),
  formatted_query String,
  query_shape String,
  hogql_shape String,
  exception_name String,
  ProfileEvents Map(String, UInt64)
) ENGINE = Distributed('ops', 'posthog', 'sharded_query_log_archive_v3');
CREATE TABLE posthog.trace_attributes (
  team_id Int32,
  original_expiry_time_bucket DateTime64(0),
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.trace_attributes', '{replica}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS index_granularity = 8192;
CREATE TABLE posthog.trace_attributes2 (
  team_id Int32,
  original_expiry_time_bucket DateTime64(0),
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 4
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.trace_attributes2', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS index_granularity = 8192;
CREATE TABLE posthog.trace_attributes_distributed (
  team_id Int32,
  original_expiry_time_bucket DateTime64(0),
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'trace_attributes');
CREATE TABLE posthog.trace_spans (
  time_bucket DateTime MATERIALIZED toStartOfInterval(timestamp, toIntervalHour(4)),
  original_expiry_timestamp DateTime64(6),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  parent_span_id String,
  is_root_span Bool MATERIALIZED replaceAll(trimRight(parent_span_id, '='), 'A', '') = '',
  trace_state String,
  name LowCardinality(String),
  kind Int8,
  flags UInt32,
  timestamp DateTime64(6),
  end_time DateTime64(6),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  duration_nano UInt64 MATERIALIZED toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000,
  status_code Int16,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  attributes_map_str Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
  dropped_attributes_count UInt32,
  dropped_events_count UInt32,
  dropped_links_count UInt32,
  events Array(String),
  links Array(String),
  _partition UInt32,
  _topic String,
  _offset UInt64,
  _bytes_uncompressed UInt64,
  _bytes_compressed UInt64,
  _record_count UInt64,
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
  PROJECTION projection_index_team_span_id (SELECT team_id, _part_offset
ORDER BY span_id),
  PROJECTION projection_index_team_trace_id (SELECT team_id, _part_offset
ORDER BY trace_id),
  PROJECTION projection_aggregate_counts (SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint),
  PROJECTION projection_aggregate_counts2 (SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  resource_fingerprint,
  is_root_span,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, is_root_span, resource_fingerprint)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.trace_spans', '{replica}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS allow_part_offset_column_in_projections = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', storage_policy = 's3_tiered', ttl_only_drop_parts = 1;
CREATE TABLE posthog.trace_spans_distributed (
  time_bucket DateTime MATERIALIZED toStartOfInterval(timestamp, toIntervalHour(4)),
  original_expiry_timestamp DateTime64(6),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  parent_span_id String,
  is_root_span Bool MATERIALIZED replaceAll(trimRight(parent_span_id, '='), 'A', '') = '',
  trace_state String,
  name LowCardinality(String),
  kind Int8,
  flags UInt32,
  timestamp DateTime64(6),
  end_time DateTime64(6),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  duration_nano UInt64 MATERIALIZED toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000,
  status_code Int16,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  attributes_map_str Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)),
  dropped_attributes_count UInt32,
  dropped_events_count UInt32,
  dropped_links_count UInt32,
  events Array(String),
  links Array(String),
  _partition UInt32,
  _topic String,
  _offset UInt64,
  _bytes_uncompressed UInt64,
  _bytes_compressed UInt64,
  _record_count UInt64
) ENGINE = Distributed('logs', 'posthog', 'trace_spans');
CREATE TABLE posthog.trace_spans_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.trace_spans_kafka_metrics', '{replica}-{shard}') ORDER BY (_topic, _partition) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.writable_query_log_archive_v3 (
  initial_query_start_time DateTime64(6, 'UTC'),
  team_id Int64,
  initial_query_id String,
  is_initial_query SimpleAggregateFunction(max, UInt8),
  hostname SimpleAggregateFunction(max, LowCardinality(String)),
  user SimpleAggregateFunction(max, LowCardinality(String)),
  type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)),
  event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  query_duration_ms SimpleAggregateFunction(max, UInt64),
  read_rows SimpleAggregateFunction(sum, UInt64),
  read_bytes SimpleAggregateFunction(sum, UInt64),
  written_rows SimpleAggregateFunction(sum, UInt64),
  written_bytes SimpleAggregateFunction(sum, UInt64),
  result_rows SimpleAggregateFunction(sum, UInt64),
  result_bytes SimpleAggregateFunction(sum, UInt64),
  memory_usage SimpleAggregateFunction(max, UInt64),
  memory_usage_sum SimpleAggregateFunction(sum, UInt64),
  peak_threads_usage SimpleAggregateFunction(sum, UInt64),
  execution_count SimpleAggregateFunction(sum, UInt64),
  current_database SimpleAggregateFunction(max, LowCardinality(String)),
  query SimpleAggregateFunction(max, String),
  normalized_query_hash SimpleAggregateFunction(max, UInt64),
  query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)),
  tables SimpleAggregateFunction(max, Array(String)),
  exception_code SimpleAggregateFunction(max, Int32),
  exception SimpleAggregateFunction(max, String),
  stack_trace SimpleAggregateFunction(max, String),
  ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64),
  lc_org_id SimpleAggregateFunction(max, String),
  lc_user_id SimpleAggregateFunction(max, Int64),
  lc_session_id SimpleAggregateFunction(max, String),
  lc_is_impersonated SimpleAggregateFunction(max, Bool),
  lc_workflow SimpleAggregateFunction(max, LowCardinality(String)),
  lc_kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_id SimpleAggregateFunction(max, String),
  lc_route_id SimpleAggregateFunction(max, String),
  lc_access_method SimpleAggregateFunction(max, LowCardinality(String)),
  lc_api_key_label SimpleAggregateFunction(max, String),
  lc_api_key_mask SimpleAggregateFunction(max, String),
  lc_query_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_product SimpleAggregateFunction(max, LowCardinality(String)),
  lc_chargeable SimpleAggregateFunction(max, Bool),
  lc_name SimpleAggregateFunction(max, String),
  lc_request_name SimpleAggregateFunction(max, String),
  lc_client_query_id SimpleAggregateFunction(max, String),
  lc_dashboard_id SimpleAggregateFunction(max, Int64),
  lc_insight_id SimpleAggregateFunction(max, Int64),
  lc_cohort_id SimpleAggregateFunction(max, Int64),
  lc_batch_export_id SimpleAggregateFunction(max, String),
  lc_experiment_id SimpleAggregateFunction(max, Int64),
  lc_experiment_feature_flag_key SimpleAggregateFunction(max, String),
  lc_alert_config_id SimpleAggregateFunction(max, String),
  lc_feature SimpleAggregateFunction(max, LowCardinality(String)),
  lc_table_id SimpleAggregateFunction(max, String),
  lc_warehouse_query SimpleAggregateFunction(max, Bool),
  lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)),
  lc_service_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_workload SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)),
  lc_query__query SimpleAggregateFunction(max, String),
  lc_query SimpleAggregateFunction(max, String),
  lc_modifiers SimpleAggregateFunction(max, String),
  lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__workflow_id SimpleAggregateFunction(max, String),
  lc_temporal__workflow_run_id SimpleAggregateFunction(max, String),
  lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_temporal__activity_id SimpleAggregateFunction(max, String),
  lc_temporal__attempt SimpleAggregateFunction(max, Int64),
  lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)),
  lc_dagster__run_id SimpleAggregateFunction(max, String),
  lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_name SimpleAggregateFunction(max, String),
  lc_experiment_metric_name SimpleAggregateFunction(max, String),
  lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_precompute_table SimpleAggregateFunction(max, String),
  lc_experiment_query_group_id SimpleAggregateFunction(max, String),
  lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)),
  lc_experiment_scan_date_from SimpleAggregateFunction(max, String),
  lc_experiment_scan_date_to SimpleAggregateFunction(max, String),
  lc_precompute_window_start SimpleAggregateFunction(max, String),
  lc_precompute_window_end SimpleAggregateFunction(max, String),
  lc_plan_fingerprint SimpleAggregateFunction(max, String),
  lc_estimated_rows SimpleAggregateFunction(max, Int64),
  lc_estimated_bytes SimpleAggregateFunction(max, Int64)
) ENGINE = Distributed('ops', 'posthog', 'query_log_archive_v3_buffer');
CREATE MATERIALIZED VIEW posthog.kafka_logs_avro_billing_metrics_mv TO posthog.logs_billing_metrics (team_id Int32, time_bucket DateTime, service_name LowCardinality(String), bytes_uncompressed SimpleAggregateFunction(sum, Float64), bytes_compressed SimpleAggregateFunction(sum, Float64), record_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
      _record_count,
      _bytes_uncompressed,
      _bytes_compressed
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name;
CREATE MATERIALIZED VIEW posthog.kafka_logs_avro_kafka_metrics_mv TO posthog.logs_kafka_metrics (_partition UInt32, _topic String, max_offset SimpleAggregateFunction(max, UInt64), max_observed_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_created_at SimpleAggregateFunction(max, DateTime), max_lag SimpleAggregateFunction(max, Decimal(18, 6))) AS SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM posthog.logs34
GROUP BY
  _partition, _topic;
CREATE MATERIALIZED VIEW posthog.kafka_trace_spans_avro_mv TO posthog.trace_spans (uuid String, trace_id String, span_id String, parent_span_id String, trace_state String, name String, kind Int8, flags UInt32, timestamp DateTime64(6), end_time DateTime64(6), observed_timestamp DateTime64(6), service_name String, resource_attributes Map(LowCardinality(String), String), instrumentation_scope String, attributes_map_str Map(LowCardinality(String), String), dropped_attributes_count UInt32, events Array(String), dropped_events_count UInt32, links Array(String), dropped_links_count UInt32, status_code Int16, team_id Int32, original_expiry_timestamp DateTime64(6)) AS SELECT
  uuid,
  trace_id,
  span_id,
  parent_span_id,
  trace_state,
  name,
  timestamp,
  end_time,
  observed_timestamp,
  service_name,
  instrumentation_scope,
  events,
  links,
  toInt8(kind) AS kind,
  toUInt32(flags) AS flags,
  toUInt32(dropped_attributes_count) AS dropped_attributes_count,
  toUInt32(dropped_events_count) AS dropped_events_count,
  toUInt32(dropped_links_count) AS dropped_links_count,
  toInt16(status_code) AS status_code,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  timestamp
  + toIntervalDay(
    if(
      (retention_days IS NOT NULL) AND (retention_days > 0),
      retention_days,
      toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
    )
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) AS _bytes_compressed
FROM posthog.kafka_trace_spans_avro;
CREATE MATERIALIZED VIEW posthog.logs34_to_log_attributes3 TO posthog.log_attributes3 (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), severity_text LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, severity_text, attributes
  );
CREATE MATERIALIZED VIEW posthog.logs34_to_pattern_buckets TO posthog.logs_pattern_buckets (team_id Int32, time_bucket DateTime('UTC'), service_name LowCardinality(String), namespace LowCardinality(String), environment LowCardinality(String), severity_text LowCardinality(String), pattern_version UInt8, pattern String, retention_days SimpleAggregateFunction(max, UInt16), log_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  time_bucket,
  service_name,
  namespace,
  environment,
  severity_text,
  pattern_version,
  pattern,
  maxSimpleState(retention_days) AS retention_days,
  sumSimpleState(1) AS log_count
FROM
  (
    SELECT
      team_id,
      toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
      service_name,
      if(
        (resource_attributes['k8s.namespace.name']) != '',
        resource_attributes['k8s.namespace.name'],
        resource_attributes['service.namespace']
      ) AS namespace,
      if(
        (resource_attributes['deployment.environment.name']) != '',
        resource_attributes['deployment.environment.name'],
        if(
          (resource_attributes['deployment.environment']) != '',
          resource_attributes['deployment.environment'],
          resource_attributes['env']
        )
      ) AS environment,
      lower(severity_text) AS severity_text,
      pattern_version,
      pattern,
      toUInt16(
        least(
          intDiv(
            greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0)
            + 86399999999,
            86400000000
          ),
          3650
        )
      ) AS retention_days
    FROM posthog.logs34
    WHERE pattern_version != 0
  )
GROUP BY
  team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version, pattern;
CREATE MATERIALIZED VIEW posthog.logs34_to_resource_attributes3 TO posthog.log_attributes3 (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), severity_text LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, severity_text, resource_attributes
  );
CREATE MATERIALIZED VIEW posthog.logs34_to_volume_buckets TO posthog.logs_volume_buckets (team_id Int32, time_bucket DateTime('UTC'), service_name LowCardinality(String), namespace LowCardinality(String), environment LowCardinality(String), severity_text LowCardinality(String), retention_days SimpleAggregateFunction(max, UInt16), log_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  time_bucket,
  service_name,
  namespace,
  environment,
  severity_text,
  maxSimpleState(retention_days) AS retention_days,
  sumSimpleState(1) AS log_count
FROM
  (
    SELECT
      team_id,
      toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
      service_name,
      if(
        (resource_attributes['k8s.namespace.name']) != '',
        resource_attributes['k8s.namespace.name'],
        resource_attributes['service.namespace']
      ) AS namespace,
      if(
        (resource_attributes['deployment.environment.name']) != '',
        resource_attributes['deployment.environment.name'],
        if(
          (resource_attributes['deployment.environment']) != '',
          resource_attributes['deployment.environment'],
          resource_attributes['env']
        )
      ) AS environment,
      lower(severity_text) AS severity_text,
      toUInt16(
        least(
          intDiv(
            greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0)
            + 86399999999,
            86400000000
          ),
          3650
        )
      ) AS retention_days
    FROM posthog.logs34
  )
GROUP BY
  team_id, time_bucket, service_name, namespace, environment, severity_text;
CREATE MATERIALIZED VIEW posthog.ops_query_log_archive_v3_mv TO posthog.writable_query_log_archive_v3 (initial_query_start_time DateTime64(6, 'UTC'), team_id Int64, initial_query_id String, is_initial_query SimpleAggregateFunction(max, UInt8), hostname SimpleAggregateFunction(max, LowCardinality(String)), user SimpleAggregateFunction(max, LowCardinality(String)), type SimpleAggregateFunction(max, Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4)), event_time_microseconds SimpleAggregateFunction(max, DateTime64(6, 'UTC')), query_duration_ms SimpleAggregateFunction(max, UInt64), read_rows SimpleAggregateFunction(sum, UInt64), read_bytes SimpleAggregateFunction(sum, UInt64), written_rows SimpleAggregateFunction(sum, UInt64), written_bytes SimpleAggregateFunction(sum, UInt64), result_rows SimpleAggregateFunction(sum, UInt64), result_bytes SimpleAggregateFunction(sum, UInt64), memory_usage SimpleAggregateFunction(max, UInt64), memory_usage_sum SimpleAggregateFunction(sum, UInt64), peak_threads_usage SimpleAggregateFunction(sum, UInt64), execution_count SimpleAggregateFunction(sum, UInt64), current_database SimpleAggregateFunction(max, LowCardinality(String)), query SimpleAggregateFunction(max, String), normalized_query_hash SimpleAggregateFunction(max, UInt64), query_kind_by_root SimpleAggregateFunction(max, Tuple(UInt8, String)), tables SimpleAggregateFunction(max, Array(String)), exception_code SimpleAggregateFunction(max, Int32), exception SimpleAggregateFunction(max, String), stack_trace SimpleAggregateFunction(max, String), ProfileEvents_SelectedRows SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_RealTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_OSCPUVirtualTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_UserTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_SystemTimeMicroseconds SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedParts SimpleAggregateFunction(sum, UInt64), ProfileEvents_SelectedMarks SimpleAggregateFunction(sum, UInt64), ProfileEvents_NetworkReceiveBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_NetworkSendBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_ReadBufferFromFileDescriptorReadBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_WriteBufferFromFileDescriptorWriteBytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3Clients SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3DeleteObjects SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CopyObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3ListObjects SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3HeadObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3GetObjectAttributes SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CreateMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3UploadPartCopy SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3UploadPart SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3AbortMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3CompleteMultipartUpload SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3PutObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_S3GetObject SimpleAggregateFunction(sum, UInt64), ProfileEvents_ReadBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64), ProfileEvents_WriteBufferFromS3Bytes SimpleAggregateFunction(sum, UInt64), lc_org_id SimpleAggregateFunction(max, String), lc_user_id SimpleAggregateFunction(max, Int64), lc_session_id SimpleAggregateFunction(max, String), lc_is_impersonated SimpleAggregateFunction(max, Bool), lc_workflow SimpleAggregateFunction(max, LowCardinality(String)), lc_kind SimpleAggregateFunction(max, LowCardinality(String)), lc_id SimpleAggregateFunction(max, String), lc_route_id SimpleAggregateFunction(max, String), lc_access_method SimpleAggregateFunction(max, LowCardinality(String)), lc_api_key_label SimpleAggregateFunction(max, String), lc_api_key_mask SimpleAggregateFunction(max, String), lc_query_type SimpleAggregateFunction(max, LowCardinality(String)), lc_product SimpleAggregateFunction(max, LowCardinality(String)), lc_chargeable SimpleAggregateFunction(max, Bool), lc_name SimpleAggregateFunction(max, String), lc_request_name SimpleAggregateFunction(max, String), lc_client_query_id SimpleAggregateFunction(max, String), lc_dashboard_id SimpleAggregateFunction(max, Int64), lc_insight_id SimpleAggregateFunction(max, Int64), lc_cohort_id SimpleAggregateFunction(max, Int64), lc_batch_export_id SimpleAggregateFunction(max, String), lc_experiment_id SimpleAggregateFunction(max, Int64), lc_experiment_feature_flag_key SimpleAggregateFunction(max, String), lc_alert_config_id SimpleAggregateFunction(max, String), lc_feature SimpleAggregateFunction(max, LowCardinality(String)), lc_table_id SimpleAggregateFunction(max, String), lc_warehouse_query SimpleAggregateFunction(max, Bool), lc_person_on_events_mode SimpleAggregateFunction(max, LowCardinality(String)), lc_service_name SimpleAggregateFunction(max, LowCardinality(String)), lc_workload SimpleAggregateFunction(max, LowCardinality(String)), lc_query__kind SimpleAggregateFunction(max, LowCardinality(String)), lc_query__query SimpleAggregateFunction(max, String), lc_query SimpleAggregateFunction(max, String), lc_modifiers SimpleAggregateFunction(max, String), lc_temporal__workflow_namespace SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__workflow_type SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__workflow_id SimpleAggregateFunction(max, String), lc_temporal__workflow_run_id SimpleAggregateFunction(max, String), lc_temporal__activity_type SimpleAggregateFunction(max, LowCardinality(String)), lc_temporal__activity_id SimpleAggregateFunction(max, String), lc_temporal__attempt SimpleAggregateFunction(max, Int64), lc_dagster__job_name SimpleAggregateFunction(max, LowCardinality(String)), lc_dagster__run_id SimpleAggregateFunction(max, String), lc_dagster__owner SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_name SimpleAggregateFunction(max, String), lc_experiment_metric_name SimpleAggregateFunction(max, String), lc_experiment_execution_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_metric_type SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_funnel_order_type SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_exposures_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_metric_events_path SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_query_surface SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_precompute_table SimpleAggregateFunction(max, String), lc_experiment_query_group_id SimpleAggregateFunction(max, String), lc_experiment_precompute_skip_reason SimpleAggregateFunction(max, LowCardinality(String)), lc_experiment_scan_date_from SimpleAggregateFunction(max, String), lc_experiment_scan_date_to SimpleAggregateFunction(max, String), lc_precompute_window_start SimpleAggregateFunction(max, String), lc_precompute_window_end SimpleAggregateFunction(max, String), lc_plan_fingerprint SimpleAggregateFunction(max, String), lc_estimated_rows SimpleAggregateFunction(max, Int64), lc_estimated_bytes SimpleAggregateFunction(max, Int64)) AS WITH
  JSONExtract(ql.log_comment, 'Tuple(team_id Int64, org_id String, user_id Int64, session_id String, is_impersonated Bool, workflow String, kind String, id String, route_id String, access_method String, api_key_label String, api_key_mask String, query_type String, product String, chargeable Bool, name String, request_name String, client_query_id String, dashboard_id Int64, insight_id Int64, cohort_id Int64, batch_export_id String, experiment_id Int64, experiment_feature_flag_key String, alert_config_id String, feature String, table_id String, warehouse_query Bool, person_on_events_mode String, service_name String, workload String, experiment_name String, experiment_metric_name String, experiment_execution_path String, experiment_metric_type String, experiment_funnel_order_type String, experiment_exposures_path String, experiment_metric_events_path String, experiment_query_surface String, experiment_precompute_table String, experiment_query_group_id String, experiment_precompute_skip_reason String, experiment_scan_date_from String, experiment_scan_date_to String, precompute_window_start String, precompute_window_end String, plan_fingerprint String, estimated_rows Int64, estimated_bytes Int64, temporal Tuple(workflow_namespace String, workflow_type String, workflow_id String, workflow_run_id String, activity_type String, activity_id String, attempt Int64), dagster Tuple(job_name String, run_id String, tags Tuple(owner String)), query Tuple(kind String, query String, source Tuple(kind String, query String)))') AS lc
SELECT
  if(
    empty(ql.initial_query_id),
    ql.query_start_time_microseconds,
    ql.initial_query_start_time_microseconds
  ) AS initial_query_start_time,
  lc.team_id AS team_id,
  if(empty(ql.initial_query_id), ql.query_id, ql.initial_query_id) AS initial_query_id,
  ql.is_initial_query AS is_initial_query,
  if(ql.is_initial_query, ql.hostname, '') AS hostname,
  ql.user AS user,
  ql.type AS type,
  ql.event_time_microseconds AS event_time_microseconds,
  if(ql.is_initial_query, ql.query_duration_ms, 0) AS query_duration_ms,
  if(ql.is_initial_query, ql.read_rows, 0) AS read_rows,
  if(ql.is_initial_query, ql.read_bytes, 0) AS read_bytes,
  if(ql.is_initial_query, ql.written_rows, 0) AS written_rows,
  if(ql.is_initial_query, ql.written_bytes, 0) AS written_bytes,
  if(ql.is_initial_query, ql.result_rows, 0) AS result_rows,
  if(ql.is_initial_query, ql.result_bytes, 0) AS result_bytes,
  ql.memory_usage AS memory_usage,
  ql.memory_usage AS memory_usage_sum,
  ql.peak_threads_usage AS peak_threads_usage,
  1 AS execution_count,
  ql.current_database AS current_database,
  if(ql.is_initial_query, ql.query, '') AS query,
  if(ql.is_initial_query, ql.normalized_query_hash, 0) AS normalized_query_hash,
  tuple(ql.is_initial_query, ql.query_kind) AS query_kind_by_root,
  if(ql.is_initial_query, ql.tables, []) AS tables,
  if(ql.is_initial_query, ql.exception_code, 0) AS exception_code,
  if(ql.is_initial_query, ql.exception, '') AS exception,
  if(ql.is_initial_query, ql.stack_trace, '') AS stack_trace,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedRows'], 0) AS ProfileEvents_SelectedRows,
  if(ql.is_initial_query, ql.ProfileEvents['SelectedBytes'], 0) AS ProfileEvents_SelectedBytes,
  ql.ProfileEvents['RealTimeMicroseconds'] AS ProfileEvents_RealTimeMicroseconds,
  ql.ProfileEvents['OSCPUVirtualTimeMicroseconds'] AS ProfileEvents_OSCPUVirtualTimeMicroseconds,
  ql.ProfileEvents['UserTimeMicroseconds'] AS ProfileEvents_UserTimeMicroseconds,
  ql.ProfileEvents['SystemTimeMicroseconds'] AS ProfileEvents_SystemTimeMicroseconds,
  ql.ProfileEvents['SelectedParts'] AS ProfileEvents_SelectedParts,
  ql.ProfileEvents['SelectedMarks'] AS ProfileEvents_SelectedMarks,
  ql.ProfileEvents['NetworkReceiveBytes'] AS ProfileEvents_NetworkReceiveBytes,
  ql.ProfileEvents['NetworkSendBytes'] AS ProfileEvents_NetworkSendBytes,
  ql.ProfileEvents['ReadBufferFromFileDescriptorReadBytes'] AS ProfileEvents_ReadBufferFromFileDescriptorReadBytes,
  ql.ProfileEvents['WriteBufferFromFileDescriptorWriteBytes'] AS ProfileEvents_WriteBufferFromFileDescriptorWriteBytes,
  ql.ProfileEvents['S3Clients'] AS ProfileEvents_S3Clients,
  ql.ProfileEvents['S3DeleteObjects'] AS ProfileEvents_S3DeleteObjects,
  ql.ProfileEvents['S3CopyObject'] AS ProfileEvents_S3CopyObject,
  ql.ProfileEvents['S3ListObjects'] AS ProfileEvents_S3ListObjects,
  ql.ProfileEvents['S3HeadObject'] AS ProfileEvents_S3HeadObject,
  ql.ProfileEvents['S3GetObjectAttributes'] AS ProfileEvents_S3GetObjectAttributes,
  ql.ProfileEvents['S3CreateMultipartUpload'] AS ProfileEvents_S3CreateMultipartUpload,
  ql.ProfileEvents['S3UploadPartCopy'] AS ProfileEvents_S3UploadPartCopy,
  ql.ProfileEvents['S3UploadPart'] AS ProfileEvents_S3UploadPart,
  ql.ProfileEvents['S3AbortMultipartUpload'] AS ProfileEvents_S3AbortMultipartUpload,
  ql.ProfileEvents['S3CompleteMultipartUpload'] AS ProfileEvents_S3CompleteMultipartUpload,
  ql.ProfileEvents['S3PutObject'] AS ProfileEvents_S3PutObject,
  ql.ProfileEvents['S3GetObject'] AS ProfileEvents_S3GetObject,
  ql.ProfileEvents['ReadBufferFromS3Bytes'] AS ProfileEvents_ReadBufferFromS3Bytes,
  ql.ProfileEvents['WriteBufferFromS3Bytes'] AS ProfileEvents_WriteBufferFromS3Bytes,
  lc.org_id AS lc_org_id,
  lc.user_id AS lc_user_id,
  lc.session_id AS lc_session_id,
  lc.is_impersonated AS lc_is_impersonated,
  lc.workflow AS lc_workflow,
  lc.kind AS lc_kind,
  lc.id AS lc_id,
  lc.route_id AS lc_route_id,
  lc.access_method AS lc_access_method,
  lc.api_key_label AS lc_api_key_label,
  lc.api_key_mask AS lc_api_key_mask,
  lc.query_type AS lc_query_type,
  lc.product AS lc_product,
  lc.chargeable AS lc_chargeable,
  lc.name AS lc_name,
  lc.request_name AS lc_request_name,
  lc.client_query_id AS lc_client_query_id,
  lc.dashboard_id AS lc_dashboard_id,
  lc.insight_id AS lc_insight_id,
  lc.cohort_id AS lc_cohort_id,
  lc.batch_export_id AS lc_batch_export_id,
  lc.experiment_id AS lc_experiment_id,
  lc.experiment_feature_flag_key AS lc_experiment_feature_flag_key,
  lc.alert_config_id AS lc_alert_config_id,
  lc.feature AS lc_feature,
  lc.table_id AS lc_table_id,
  lc.warehouse_query AS lc_warehouse_query,
  lc.person_on_events_mode AS lc_person_on_events_mode,
  lc.service_name AS lc_service_name,
  lc.workload AS lc_workload,
  if(notEmpty(lc.query.source.kind), lc.query.source.kind, lc.query.kind) AS lc_query__kind,
  if(
    ql.is_initial_query,
    if(notEmpty(lc.query.source.kind), lc.query.source.query, lc.query.query),
    ''
  ) AS lc_query__query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'query'), '') AS lc_query,
  if(ql.is_initial_query, JSONExtractRaw(ql.log_comment, 'modifiers'), '') AS lc_modifiers,
  lc.temporal.workflow_namespace AS lc_temporal__workflow_namespace,
  lc.temporal.workflow_type AS lc_temporal__workflow_type,
  lc.temporal.workflow_id AS lc_temporal__workflow_id,
  lc.temporal.workflow_run_id AS lc_temporal__workflow_run_id,
  lc.temporal.activity_type AS lc_temporal__activity_type,
  lc.temporal.activity_id AS lc_temporal__activity_id,
  lc.temporal.attempt AS lc_temporal__attempt,
  lc.dagster.job_name AS lc_dagster__job_name,
  lc.dagster.run_id AS lc_dagster__run_id,
  lc.dagster.tags.owner AS lc_dagster__owner,
  lc.experiment_name AS lc_experiment_name,
  lc.experiment_metric_name AS lc_experiment_metric_name,
  lc.experiment_execution_path AS lc_experiment_execution_path,
  lc.experiment_metric_type AS lc_experiment_metric_type,
  lc.experiment_funnel_order_type AS lc_experiment_funnel_order_type,
  lc.experiment_exposures_path AS lc_experiment_exposures_path,
  lc.experiment_metric_events_path AS lc_experiment_metric_events_path,
  lc.experiment_query_surface AS lc_experiment_query_surface,
  lc.experiment_precompute_table AS lc_experiment_precompute_table,
  lc.experiment_query_group_id AS lc_experiment_query_group_id,
  lc.experiment_precompute_skip_reason AS lc_experiment_precompute_skip_reason,
  lc.experiment_scan_date_from AS lc_experiment_scan_date_from,
  lc.experiment_scan_date_to AS lc_experiment_scan_date_to,
  lc.precompute_window_start AS lc_precompute_window_start,
  lc.precompute_window_end AS lc_precompute_window_end,
  lc.plan_fingerprint AS lc_plan_fingerprint,
  lc.estimated_rows AS lc_estimated_rows,
  lc.estimated_bytes AS lc_estimated_bytes
FROM system.query_log AS ql
WHERE ql.type != 'QueryStart';
CREATE MATERIALIZED VIEW posthog.trace_span_to_attributes TO posthog.trace_attributes (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span_attribute' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, attribute
  );
CREATE MATERIALIZED VIEW posthog.trace_span_to_attributes2 TO posthog.trace_attributes2 (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span_attribute' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, attribute
  );
CREATE MATERIALIZED VIEW posthog.trace_span_to_resource_attributes TO posthog.trace_attributes (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span_resource_attribute' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, attribute
  );
CREATE MATERIALIZED VIEW posthog.trace_span_to_resource_attributes2 TO posthog.trace_attributes2 (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span_resource_attribute' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, attribute
  );
CREATE MATERIALIZED VIEW posthog.trace_span_to_span_attributes TO posthog.trace_attributes (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      'name' AS attribute_key,
      name AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, name
  );
CREATE MATERIALIZED VIEW posthog.trace_span_to_span_attributes2 TO posthog.trace_attributes2 (team_id Int32, original_expiry_time_bucket DateTime64(0), time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  original_expiry_time_bucket,
  time_bucket,
  service_name,
  resource_fingerprint,
  attribute_key,
  attribute_value,
  'span' AS attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
      toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
      service_name AS service_name,
      resource_fingerprint,
      'name' AS attribute_key,
      name AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.trace_spans
    GROUP BY
      team_id, original_expiry_time_bucket, time_bucket, service_name, resource_fingerprint, name
  );
CREATE MATERIALIZED VIEW posthog.trace_spans_to_kafka_metrics_mv TO posthog.trace_spans_kafka_metrics (_partition UInt64, _topic LowCardinality(String), max_offset SimpleAggregateFunction(max, UInt64), max_observed_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_created_at SimpleAggregateFunction(max, DateTime), max_lag SimpleAggregateFunction(max, Decimal(18, 6))) AS SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM posthog.trace_spans
GROUP BY
  _partition, _topic;
CREATE VIEW posthog.custom_metrics_backups AS WITH
  ['ClickHouseCustomMetric_BackupFailed', 'ClickHouseCustomMetric_BackupSuccess', 'ClickHouseCustomMetric_BackupCancelled', 'ClickHouseCustomMetric_BackupAttempts'] AS names,
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS `values`,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.backup_log
WHERE event_date = today()
GROUP BY
  event_date;
CREATE VIEW posthog.custom_metrics_dictionaries AS SELECT
  'ClickHouseCustomMetric_DictionariesFailed' AS name,
  map(
    'instance',
    hostname(),
    'database',
    d.database,
    'dictionary',
    d.dict_name,
    'uuid',
    toString(d.uuid),
    'status',
    toString(d.status)
  ) AS labels,
  toUInt64(1) AS value,
  'Dictionary is in FAILED or FAILED_AND_RELOADING status' AS help,
  'gauge' AS type
FROM
  (
    SELECT name AS dict_name, database, uuid, status
    FROM system.dictionaries
    WHERE status IN ('FAILED', 'FAILED_AND_RELOADING')
  ) AS d;
CREATE VIEW posthog.custom_metrics_part_counts AS SELECT
  'ClickHouseCustomMetric_MaxPartCountPerPartition' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`, 'partition', partition) AS labels,
  part_count AS value,
  'Maximum number of active parts for any partition in a PostHog table' AS help,
  'gauge' AS type
FROM
  (
    SELECT database, `table`, partition, count() AS part_count
    FROM system.parts
    WHERE
      active
    AND
      (database = 'posthog')
    GROUP BY
      database, `table`, partition
    ORDER BY database ASC, `table` ASC, part_count DESC, partition ASC
    LIMIT 1 BY database, `table`
  );
CREATE VIEW posthog.custom_metrics_replication_queue AS WITH
  ['ClickHouseCustomMetric_ReplicationQueueStuckEntries', 'ClickHouseCustomMetric_ReplicationQueueMaxPostponedEntrySeconds', 'ClickHouseCustomMetric_ReplicationQueueMaxErrorEntrySeconds'] AS names,
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS `values`,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, `values`, descriptions, types)) AS tpl
SELECT
  tpl.1 AS name,
  map('table', `table`, 'instance', hostname()) AS labels,
  tpl.2 AS value,
  tpl.3 AS help,
  tpl.4 AS type
FROM system.replication_queue
GROUP BY
  `table`
HAVING
  value > 0;
CREATE VIEW posthog.custom_metrics_server_crash AS SELECT
  'ClickHouseCustomMetric_ServerCrash' AS name,
  map('instance', hostname()) AS labels,
  count() AS value,
  'Number of server crashes for current date' AS help,
  'gauge' AS type
FROM system.crash_log
WHERE event_date = today()
GROUP BY
  hostname();
CREATE VIEW posthog.custom_metrics_table_sizes AS SELECT
  'ClickHouseCustomMetric_TableTotalBytes' AS name,
  map('instance', hostname(), 'database', database, 'table', `table`) AS labels,
  CAST(total_bytes, 'Float64') AS value,
  'Size of a database table on a given node (need a sum for sharded)' AS help,
  'gauge' AS type
FROM system.tables
WHERE
  (database NOT IN ('INFORMATION_SCHEMA', 'information_schema'))
AND
  (total_bytes IS NOT NULL);
CREATE VIEW posthog.custom_metrics_test AS SELECT
  'ClickHouseCustomMetric_Test' AS name,
  map('instance', hostname()) AS labels,
  1 AS value,
  'Test to check that the metric endpoint is working' AS help,
  'gauge' AS type;
CREATE VIEW posthog.metrics4_view AS SELECT
  team_id,
  metric_name,
  time_bucket,
  series_fingerprint,
  resource_fingerprint,
  timestamp,
  observed_timestamp,
  original_expiry_timestamp,
  service_name,
  metric_type,
  value,
  count,
  histogram_bounds,
  histogram_counts,
  trace_id,
  span_id,
  trace_flags,
  has_labels,
  unit,
  aggregation_temporality,
  is_monotonic,
  instrumentation_scope
FROM posthog.metrics2
WHERE
  (time_bucket > toDateTime('2026-08-25 00:00:00'))
AND
  (time_bucket < toDateTime('2026-09-14 00:00:00'))
AND
  (timestamp > toDateTime('2026-08-25 00:00:00'))
AND
  (timestamp < toDateTime('2026-09-14 00:00:00'))
UNION ALL
SELECT
  team_id,
  metric_name,
  time_bucket,
  series_fingerprint,
  resource_fingerprint,
  point_timestamp AS timestamp,
  point_observed_timestamp AS observed_timestamp,
  toDateTime64(original_expiry_date, 6) AS original_expiry_timestamp,
  service_name,
  metric_type,
  point_value AS value,
  point_count AS count,
  histogram_bounds,
  point_histogram_counts AS histogram_counts,
  point_trace_id AS trace_id,
  point_span_id AS span_id,
  point_trace_flags AS trace_flags,
  toBool(has_labels) AS has_labels,
  unit,
  aggregation_temporality,
  toBool(is_monotonic) AS is_monotonic,
  instrumentation_scope
FROM
  posthog.metrics4_samples ARRAY JOIN timestamp_arr AS point_timestamp, observed_timestamp_arr AS point_observed_timestamp, value_arr AS point_value, count_arr AS point_count, histogram_counts_arr AS point_histogram_counts, trace_id_arr AS point_trace_id, span_id_arr AS point_span_id, trace_flags_arr AS point_trace_flags
WHERE time_bucket >= toDateTime('2026-09-14 00:00:00');
CREATE TABLE posthog.metric_samples (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  timestamp DateTime64(6) CODEC(DoubleDelta),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1,
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  trace_id String,
  span_id String,
  trace_flags Int32
) ENGINE = Distributed('logs', 'posthog', 'metric_samples1');
CREATE TABLE posthog.metric_series (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6) CODEC(DoubleDelta)
) ENGINE = Distributed('logs', 'posthog', 'metric_series1');
CREATE TABLE posthog.metrics (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp),
  uuid String,
  team_id Int32,
  trace_id String,
  span_id String,
  trace_flags Int32,
  timestamp DateTime64(6),
  observed_timestamp DateTime64(6),
  created_at DateTime64(6) MATERIALIZED now(),
  service_name LowCardinality(String),
  metric_name LowCardinality(String),
  metric_type LowCardinality(String),
  value Float64 CODEC(Gorilla(8)),
  count UInt64 DEFAULT 1 CODEC(T64),
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool DEFAULT false,
  resource_attributes Map(LowCardinality(String), String),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes),
  instrumentation_scope String,
  attributes_map_str Map(LowCardinality(String), String),
  attributes_map_float Map(LowCardinality(String), Float64),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(String, String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str)
) ENGINE = Distributed('logs', 'posthog', 'metrics1');
CREATE VIEW posthog.custom_metrics AS SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_test
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_replication_queue
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_server_crash
UNION ALL
SELECT *
FROM posthog.custom_metrics_table_sizes
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_part_counts
UNION ALL
SELECT * REPLACE(toFloat64(value) AS value)
FROM posthog.custom_metrics_dictionaries
UNION ALL
SELECT
  'ClickHouseCustomMetric_S3DiskBytesUsed' AS name,
  map('instance', hostname(), 'disk', disk_name) AS labels,
  toFloat64(sum(bytes_on_disk)) AS value,
  'Bytes currently used by ClickHouse parts on S3-backed disks on this node' AS help,
  'gauge' AS type
FROM system.parts
WHERE disk_name IN ('s3disk', 'cache')
GROUP BY
  disk_name
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeFailures15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(count()) AS value,
  'Number of failed merge operations in the last 15 minutes' AS help,
  'gauge' AS type
FROM system.part_log
WHERE
  (event_time >= (now() - toIntervalMinute(15)))
AND
  (event_type = 'MergeParts')
AND
  (error > 0)
AND
  (merge_reason != 'NotAMerge')
AND
  (error != 40)
UNION ALL
SELECT
  'ClickHouseCustomMetric_MergeRetriesMaxPerTable15m' AS name,
  map('instance', hostname()) AS labels,
  toFloat64(max(cnt)) AS value,
  'Max failed merge retries for any single table in the last 15 minutes' AS help,
  'gauge' AS type
FROM
  (
    SELECT count() AS cnt
    FROM system.part_log
    WHERE
      (event_time >= (now() - toIntervalMinute(15)))
    AND
      (event_type = 'MergeParts')
    AND
      (error > 0)
    AND
      (merge_reason != 'NotAMerge')
    AND
      (error != 40)
    GROUP BY
      database, `table`, partition_id
  );
