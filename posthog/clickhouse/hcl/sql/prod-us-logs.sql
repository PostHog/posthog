-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the prod-us/logs node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.kafka_logs_avro (
  uuid String,
  trace_id String,
  span_id String,
  trace_flags Int32,
  timestamp DateTime64(6),
  observed_timestamp DateTime64(6),
  body String,
  severity_text String,
  severity_number Int32,
  service_name String,
  resource_attributes Map(LowCardinality(String), String),
  instrumentation_scope String,
  event_name String,
  attributes Map(LowCardinality(String), String)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_logs', kafka_format = 'kafka_format = \'Avro\'', kafka_group_name = 'kafka_group_name = \'clickhouse-logs-avro-new\'', kafka_num_consumers = 32, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_logs\'';
CREATE TABLE posthog.kafka_metrics_avro (
  uuid String,
  trace_id String,
  span_id String,
  trace_flags Nullable(Int32),
  timestamp DateTime64(6),
  observed_timestamp DateTime64(6),
  service_name Nullable(String),
  metric_name Nullable(String),
  metric_type Nullable(String),
  value Nullable(Float64),
  count Nullable(Int64),
  histogram_bounds Array(Float64),
  histogram_counts Array(Int64),
  unit Nullable(String),
  aggregation_temporality Nullable(String),
  is_monotonic Nullable(UInt8),
  resource_attributes Map(String, String),
  instrumentation_scope Nullable(String),
  attributes Map(String, String),
  series_fingerprint Nullable(Int64)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_metrics', kafka_format = 'kafka_format = \'Avro\'', kafka_group_name = 'kafka_group_name = \'clickhouse-metrics-avro-new\'', kafka_num_consumers = 8, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_metrics\'';
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
  status_code Int32
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_traces', kafka_format = 'kafka_format = \'Avro\'', kafka_group_name = 'kafka_group_name = \'clickhouse-traces-avro\'', kafka_num_consumers = 8, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_traces\'';
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
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/logs/{shard}/log_attributes34', '{replica}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(time_bucket) TTL time_bucket + toIntervalDay(15) SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192;
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
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes3', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192;
CREATE TABLE posthog.log_attributes_distributed (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  resource_fingerprint UInt64 DEFAULT 0,
  attribute_key LowCardinality(String),
  attribute_value String CODEC(ZSTD(5)),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String) DEFAULT 'log',
  original_expiry_time_bucket DateTime DEFAULT now()
) ENGINE = Distributed('logs', 'posthog', 'log_attributes2');
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
  INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
  INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
  INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
  INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
  INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.logs34', '{replica}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_buckets_strategy = 'constant', map_serialization_version = 'with_buckets', max_buckets_in_map = 32, storage_policy = 's3_tiered', ttl_only_drop_parts = 1;
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
  _record_count UInt64
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
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.metrics1', '{replica}') ORDER BY (team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp) PARTITION BY toDate(timestamp) SETTINGS index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1;
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
  hostname LowCardinality(String),
  user LowCardinality(String),
  query_id String,
  initial_query_id String,
  is_initial_query UInt8,
  type Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4),
  event_date Date,
  event_time DateTime,
  event_time_microseconds DateTime64(6),
  query_start_time DateTime,
  query_start_time_microseconds DateTime64(6),
  query_duration_ms UInt64,
  read_rows UInt64,
  read_bytes UInt64,
  written_rows UInt64,
  written_bytes UInt64,
  result_rows UInt64,
  result_bytes UInt64,
  memory_usage UInt64,
  peak_threads_usage UInt64,
  current_database LowCardinality(String),
  query String,
  formatted_query String,
  normalized_query_hash UInt64,
  query_kind LowCardinality(String),
  exception_code Int32,
  exception String,
  stack_trace String,
  team_id Int64,
  log_comment JSON(max_dynamic_paths=256, access_method LowCardinality(String), alert_config_id String, api_key_label String, api_key_mask String, batch_export_id String, chargeable Bool, client_query_id String, cohort_id Int64, `dagster.job_name` String, `dagster.run_id` String, `dagster.tags.owner` String, dashboard_id Int64, experiment_feature_flag_key String, experiment_id Int64, feature LowCardinality(String), id String, insight_id Int64, is_impersonated Bool, kind LowCardinality(String), name String, org_id String, person_on_events_mode LowCardinality(String), product LowCardinality(String), query_type LowCardinality(String), request_name String, route_id String, service_name String, session_id String, table_id String, team_id Int64, `temporal.activity_id` String, `temporal.activity_type` String, `temporal.attempt` Int64, `temporal.workflow_id` String, `temporal.workflow_namespace` String, `temporal.workflow_run_id` String, `temporal.workflow_type` String, user_id Int64, warehouse_query Bool, workflow LowCardinality(String), workload LowCardinality(String), SKIP cache_key, SKIP filter, SKIP hogql_features, SKIP http_referer, SKIP http_request_id, SKIP http_user_agent, SKIP query_settings, SKIP timings, SKIP user_email),
  ProfileEvents Map(String, UInt64),
  exception_name String ALIAS errorCodeToName(exception_code),
  ProfileEvents_RealTimeMicroseconds Int64 ALIAS ProfileEvents['RealTimeMicroseconds'],
  ProfileEvents_OSCPUVirtualTimeMicroseconds Int64 ALIAS ProfileEvents['OSCPUVirtualTimeMicroseconds'],
  ProfileEvents_S3Clients Int64 ALIAS ProfileEvents['S3Clients'],
  ProfileEvents_S3DeleteObjects Int64 ALIAS ProfileEvents['S3DeleteObjects'],
  ProfileEvents_S3CopyObject Int64 ALIAS ProfileEvents['S3CopyObject'],
  ProfileEvents_S3ListObjects Int64 ALIAS ProfileEvents['S3ListObjects'],
  ProfileEvents_S3HeadObject Int64 ALIAS ProfileEvents['S3HeadObject'],
  ProfileEvents_S3GetObjectAttributes Int64 ALIAS ProfileEvents['S3GetObjectAttributes'],
  ProfileEvents_S3CreateMultipartUpload Int64 ALIAS ProfileEvents['S3CreateMultipartUpload'],
  ProfileEvents_S3UploadPartCopy Int64 ALIAS ProfileEvents['S3UploadPartCopy'],
  ProfileEvents_S3UploadPart Int64 ALIAS ProfileEvents['S3UploadPart'],
  ProfileEvents_S3AbortMultipartUpload Int64 ALIAS ProfileEvents['S3AbortMultipartUpload'],
  ProfileEvents_S3CompleteMultipartUpload Int64 ALIAS ProfileEvents['S3CompleteMultipartUpload'],
  ProfileEvents_S3PutObject Int64 ALIAS ProfileEvents['S3PutObject'],
  ProfileEvents_S3GetObject Int64 ALIAS ProfileEvents['S3GetObject'],
  ProfileEvents_ReadBufferFromS3Bytes Int64 ALIAS ProfileEvents['ReadBufferFromS3Bytes'],
  ProfileEvents_WriteBufferFromS3Bytes Int64 ALIAS ProfileEvents['WriteBufferFromS3Bytes'],
  lc_workflow LowCardinality(String) ALIAS log_comment.workflow,
  lc_kind LowCardinality(String) ALIAS log_comment.kind,
  lc_id String ALIAS CAST(log_comment.id, 'String'),
  lc_route_id String ALIAS CAST(log_comment.route_id, 'String'),
  lc_access_method LowCardinality(String) ALIAS log_comment.access_method,
  lc_api_key_label String ALIAS CAST(log_comment.api_key_label, 'String'),
  lc_api_key_mask String ALIAS CAST(log_comment.api_key_mask, 'String'),
  lc_query_type LowCardinality(String) ALIAS log_comment.query_type,
  lc_product LowCardinality(String) ALIAS log_comment.product,
  lc_chargeable Bool ALIAS log_comment.chargeable,
  lc_name String ALIAS CAST(log_comment.name, 'String'),
  lc_request_name String ALIAS CAST(log_comment.request_name, 'String'),
  lc_client_query_id String ALIAS CAST(log_comment.client_query_id, 'String'),
  lc_org_id String ALIAS CAST(log_comment.org_id, 'String'),
  lc_user_id Int64 ALIAS log_comment.user_id,
  lc_is_impersonated Bool ALIAS log_comment.is_impersonated,
  lc_session_id String ALIAS CAST(log_comment.session_id, 'String'),
  lc_dashboard_id Int64 ALIAS log_comment.dashboard_id,
  lc_insight_id Int64 ALIAS log_comment.insight_id,
  lc_cohort_id Int64 ALIAS log_comment.cohort_id,
  lc_batch_export_id String ALIAS CAST(log_comment.batch_export_id, 'String'),
  lc_experiment_id Int64 ALIAS log_comment.experiment_id,
  lc_experiment_feature_flag_key String ALIAS CAST(log_comment.experiment_feature_flag_key, 'String'),
  lc_alert_config_id String ALIAS CAST(log_comment.alert_config_id, 'String'),
  lc_feature LowCardinality(String) ALIAS log_comment.feature,
  lc_table_id String ALIAS CAST(log_comment.table_id, 'String'),
  lc_warehouse_query Bool ALIAS log_comment.warehouse_query,
  lc_person_on_events_mode LowCardinality(String) ALIAS log_comment.person_on_events_mode,
  lc_service_name String ALIAS CAST(log_comment.service_name, 'String'),
  lc_workload LowCardinality(String) ALIAS log_comment.workload,
  lc_query__kind LowCardinality(String) ALIAS if(JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'kind'), JSONExtractString(toString(log_comment), 'query', 'kind')),
  lc_query__query String ALIAS multiIf(NOT is_initial_query, '', JSONHas(toString(log_comment), 'query', 'source'), JSONExtractString(toString(log_comment), 'query', 'source', 'query'), JSONExtractString(toString(log_comment), 'query', 'query')),
  lc_query String ALIAS if(is_initial_query, JSONExtractRaw(toString(log_comment), 'query'), ''),
  lc_temporal__workflow_namespace String ALIAS CAST(log_comment.`temporal.workflow_namespace`, 'String'),
  lc_temporal__workflow_type String ALIAS CAST(log_comment.`temporal.workflow_type`, 'String'),
  lc_temporal__workflow_id String ALIAS CAST(log_comment.`temporal.workflow_id`, 'String'),
  lc_temporal__workflow_run_id String ALIAS CAST(log_comment.`temporal.workflow_run_id`, 'String'),
  lc_temporal__activity_type String ALIAS CAST(log_comment.`temporal.activity_type`, 'String'),
  lc_temporal__activity_id String ALIAS CAST(log_comment.`temporal.activity_id`, 'String'),
  lc_temporal__attempt Int64 ALIAS log_comment.`temporal.attempt`,
  lc_dagster__job_name String ALIAS CAST(log_comment.`dagster.job_name`, 'String'),
  lc_dagster__run_id String ALIAS CAST(log_comment.`dagster.run_id`, 'String'),
  lc_dagster__owner String ALIAS CAST(log_comment.`dagster.tags.owner`, 'String'),
  lc_modifiers String ALIAS if(is_initial_query, JSONExtractRaw(toString(log_comment), 'modifiers'), '')
) ENGINE = Distributed('ops', 'posthog', 'sharded_query_log_archive');
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
  INDEX idx_trace_bloom_part trace_id TYPE bloom_filter(0.00001) GRANULARITY 99999,
  INDEX idx_span_id_bloom_part span_id TYPE bloom_filter(0.00001) GRANULARITY 99999
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.trace_spans', '{replica}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS allow_part_offset_column_in_projections = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1;
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
  links Array(String)
) ENGINE = Distributed('logs', 'posthog', 'trace_spans');
CREATE TABLE posthog.trace_spans_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/logs/{shard}/posthog.trace_spans_kafka_metrics', '{replica}') ORDER BY (_topic, _partition) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.writable_query_log_archive (
  hostname LowCardinality(String),
  user LowCardinality(String),
  query_id String,
  initial_query_id String,
  is_initial_query UInt8,
  type Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4),
  event_date Date,
  event_time DateTime,
  event_time_microseconds DateTime64(6),
  query_start_time DateTime,
  query_start_time_microseconds DateTime64(6),
  query_duration_ms UInt64,
  read_rows UInt64,
  read_bytes UInt64,
  written_rows UInt64,
  written_bytes UInt64,
  result_rows UInt64,
  result_bytes UInt64,
  memory_usage UInt64,
  peak_threads_usage UInt64,
  current_database LowCardinality(String),
  query String,
  formatted_query String,
  normalized_query_hash UInt64,
  query_kind LowCardinality(String),
  exception_code Int32,
  exception String,
  stack_trace String,
  team_id Int64,
  log_comment JSON(max_dynamic_paths=256, access_method LowCardinality(String), alert_config_id String, api_key_label String, api_key_mask String, batch_export_id String, chargeable Bool, client_query_id String, cohort_id Int64, `dagster.job_name` String, `dagster.run_id` String, `dagster.tags.owner` String, dashboard_id Int64, experiment_feature_flag_key String, experiment_id Int64, feature LowCardinality(String), id String, insight_id Int64, is_impersonated Bool, kind LowCardinality(String), name String, org_id String, person_on_events_mode LowCardinality(String), product LowCardinality(String), query_type LowCardinality(String), request_name String, route_id String, service_name String, session_id String, table_id String, team_id Int64, `temporal.activity_id` String, `temporal.activity_type` String, `temporal.attempt` Int64, `temporal.workflow_id` String, `temporal.workflow_namespace` String, `temporal.workflow_run_id` String, `temporal.workflow_type` String, user_id Int64, warehouse_query Bool, workflow LowCardinality(String), workload LowCardinality(String), SKIP cache_key, SKIP filter, SKIP hogql_features, SKIP http_referer, SKIP http_request_id, SKIP http_user_agent, SKIP query_settings, SKIP timings, SKIP user_email),
  ProfileEvents Map(String, UInt64)
) ENGINE = Distributed('ops', 'posthog', 'query_log_archive_buffer');
CREATE MATERIALIZED VIEW posthog.kafka_logs34_avro_mv TO posthog.logs34 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), body String, severity_text String, severity_number Int32, service_name String, instrumentation_scope String, event_name String, attributes_map_str Map(String, String), resource_attributes Map(String, String), team_id Int32, original_expiry_timestamp DateTime64(6), _partition UInt64, _topic LowCardinality(String), _offset UInt64, _record_count Int64, _bytes_uncompressed Nullable(Int64), _bytes_compressed Nullable(Int64)) AS SELECT
  kafka_logs_avro.* EXCEPT(created_at, attribute_values, attribute_keys, attributes, attributes_map_str, attributes_map_float, attributes_map_datetime, resource_attributes),
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  observed_timestamp
  + toIntervalDay(
    toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed
FROM posthog.kafka_logs_avro;
CREATE MATERIALIZED VIEW posthog.kafka_logs_avro_billing_metrics_mv TO posthog.logs_billing_metrics (team_id Int32, time_bucket DateTime, service_name LowCardinality(String), bytes_uncompressed SimpleAggregateFunction(sum, Float64), bytes_compressed SimpleAggregateFunction(sum, Float64), record_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  time_bucket,
  service_name,
  sumSimpleState(floor(_bytes_uncompressed / _record_count)) AS bytes_uncompressed,
  sumSimpleState(floor(_bytes_compressed / _record_count)) AS bytes_compressed,
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
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_kafka_metrics_mv TO posthog.metrics_kafka_metrics (_partition UInt64, _topic LowCardinality(String), max_offset SimpleAggregateFunction(max, UInt64), max_observed_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_created_at SimpleAggregateFunction(max, DateTime), max_lag SimpleAggregateFunction(max, Decimal(18, 6))) AS SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM posthog.kafka_metrics_avro
GROUP BY
  _partition, _topic;
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_mv TO posthog.metrics1 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), service_name String, metric_name String, metric_type String, value Float64, count UInt64, histogram_bounds Array(Float64), histogram_counts Array(UInt64), unit String, aggregation_temporality String, is_monotonic UInt8, resource_attributes Map(String, String), instrumentation_scope String, attributes_map_str Map(String, String), attributes_map_float Map(String, Nullable(Float64)), team_id Int32) AS SELECT
  uuid,
  trace_id,
  span_id,
  ifNull(trace_flags, 0) AS trace_flags,
  timestamp,
  observed_timestamp,
  ifNull(service_name, '') AS service_name,
  ifNull(metric_name, '') AS metric_name,
  ifNull(metric_type, '') AS metric_type,
  ifNull(value, 0) AS value,
  toUInt64(ifNull(count, 1)) AS count,
  histogram_bounds,
  arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
  ifNull(unit, '') AS unit,
  ifNull(aggregation_temporality, '') AS aggregation_temporality,
  ifNull(is_monotonic, 0) AS is_monotonic,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  ifNull(instrumentation_scope, '') AS instrumentation_scope,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(
    mapFilter(
      (k, v) -> isNotNull(v),
      mapApply(
        (k, v) -> (concat(k, '__float'), toFloat64OrNull(JSONExtract(v, 'String'))),
        attributes
      )
    )
  ) AS attributes_map_float,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id
FROM posthog.kafka_metrics_avro
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0;
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_to_metric_samples TO posthog.metric_samples1 (team_id Int32, metric_name String, series_fingerprint UInt64, timestamp DateTime64(6), value Float64, count UInt64, histogram_bounds Array(Float64), histogram_counts Array(UInt64), trace_id String, span_id String, trace_flags Int32) AS SELECT
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  ifNull(metric_name, '') AS metric_name,
  reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
  timestamp,
  ifNull(value, 0) AS value,
  toUInt64(ifNull(count, 1)) AS count,
  histogram_bounds,
  arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
  trace_id,
  span_id,
  ifNull(trace_flags, 0) AS trace_flags
FROM posthog.kafka_metrics_avro
WHERE kafka_metrics_avro.series_fingerprint IS NOT NULL
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0;
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_to_metric_series TO posthog.metric_series1 (team_id Int32, metric_name String, series_fingerprint UInt64, metric_type String, unit String, aggregation_temporality String, is_monotonic UInt8, service_name String, resource_attributes Map(String, String), attributes Map(String, String), last_seen DateTime64(6)) AS SELECT
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  ifNull(metric_name, '') AS metric_name,
  reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
  ifNull(metric_type, '') AS metric_type,
  ifNull(unit, '') AS unit,
  ifNull(aggregation_temporality, '') AS aggregation_temporality,
  ifNull(is_monotonic, 0) AS is_monotonic,
  ifNull(service_name, '') AS service_name,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)) AS attributes,
  timestamp AS last_seen
FROM posthog.kafka_metrics_avro
WHERE kafka_metrics_avro.series_fingerprint IS NOT NULL
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0;
CREATE MATERIALIZED VIEW posthog.kafka_trace_spans_avro_mv TO posthog.trace_spans (uuid String, trace_id String, span_id String, parent_span_id String, trace_state String, name String, kind Int8, flags UInt32, timestamp DateTime64(6), end_time DateTime64(6), observed_timestamp DateTime64(6), service_name String, resource_attributes Map(LowCardinality(String), String), instrumentation_scope String, attributes_map_str Map(LowCardinality(String), String), dropped_attributes_count UInt32, events Array(String), dropped_events_count UInt32, links Array(String), dropped_links_count UInt32, status_code Int16, team_id Int32) AS SELECT
  * EXCEPT(attributes, resource_attributes, kind, flags, dropped_attributes_count, dropped_events_count, dropped_links_count, status_code),
  toInt8(kind) AS kind,
  toUInt32(flags) AS flags,
  toUInt32(dropped_attributes_count) AS dropped_attributes_count,
  toUInt32(dropped_events_count) AS dropped_events_count,
  toUInt32(dropped_links_count) AS dropped_links_count,
  toInt16(status_code) AS status_code,
  mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
  mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) AS _bytes_compressed
FROM posthog.kafka_trace_spans_avro;
CREATE MATERIALIZED VIEW posthog.logs34_to_log_attributes TO posthog.log_attributes2 (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes
  );
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
CREATE MATERIALIZED VIEW posthog.logs34_to_resource_attributes TO posthog.log_attributes2 (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs34
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes
  );
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
CREATE MATERIALIZED VIEW posthog.metrics1_to_metric_attributes TO posthog.metric_attributes (team_id Int32, time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  time_bucket,
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
      service_name AS service_name,
      resource_fingerprint,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
      arrayJoin(attributes) AS attribute,
      'metric' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics1
    GROUP BY
      team_id, time_bucket, service_name, resource_fingerprint, attributes
  );
CREATE MATERIALIZED VIEW posthog.metrics1_to_resource_attributes TO posthog.metric_attributes (team_id Int32, time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  time_bucket,
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
      service_name AS service_name,
      resource_fingerprint,
      arrayJoin(resource_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics1
    GROUP BY
      team_id, time_bucket, service_name, resource_fingerprint, resource_attributes
  );
CREATE MATERIALIZED VIEW posthog.ops_query_log_archive_mv TO posthog.writable_query_log_archive (hostname LowCardinality(String), user LowCardinality(String), query_id String, initial_query_id String, is_initial_query UInt8, type Enum8('QueryStart'=1, 'QueryFinish'=2, 'ExceptionBeforeStart'=3, 'ExceptionWhileProcessing'=4), event_date Date, event_time DateTime, event_time_microseconds DateTime64(6), query_start_time DateTime, query_start_time_microseconds DateTime64(6), query_duration_ms UInt64, read_rows UInt64, read_bytes UInt64, written_rows UInt64, written_bytes UInt64, result_rows UInt64, result_bytes UInt64, memory_usage UInt64, peak_threads_usage UInt64, current_database LowCardinality(String), query String, formatted_query String, normalized_query_hash UInt64, query_kind LowCardinality(String), exception_code Int32, exception String, stack_trace String, team_id Int64, log_comment String, ProfileEvents Map(LowCardinality(String), UInt64)) AS SELECT
  hostname,
  user,
  query_id,
  initial_query_id,
  is_initial_query,
  type,
  event_date,
  event_time,
  event_time_microseconds,
  query_start_time,
  query_start_time_microseconds,
  query_duration_ms,
  read_rows,
  read_bytes,
  written_rows,
  written_bytes,
  result_rows,
  result_bytes,
  memory_usage,
  peak_threads_usage,
  current_database,
  query,
  formatted_query,
  normalized_query_hash,
  query_kind,
  exception_code,
  exception,
  stack_trace,
  JSONExtractInt(log_comment, 'team_id') AS team_id,
  if(isValidJSON(log_comment), log_comment, '{}') AS log_comment,
  ProfileEvents
FROM system.query_log
WHERE type != 'QueryStart';
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
  [toInt64(countIf(status = 'BACKUP_FAILED')), toInt64(countIf(status = 'BACKUP_CREATED')), toInt64(countIf(status = 'BACKUP_CANCELLED')), toInt64(countIf(status = 'CREATING_BACKUP'))] AS values,
  ['Number of failed backups', 'Number of successful backups', 'Number of cancelled backups', 'Number of backup attempts'] AS descriptions,
  ['gauge', 'gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
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
  [toInt64(countIf(create_time < (now() - toIntervalDay(15)))), maxIf(dateDiff('seconds', create_time, last_postpone_time), last_postpone_time != '1970-01-01'), maxIf(dateDiff('seconds', create_time, last_exception_time), (last_exception_time != '1970-01-01') AND (last_exception_time > (now() - toIntervalMinute(5))))] AS values,
  ['Number of entries that have been in the replication queue for more than 15 days', 'Maximum number of seconds that an entry has been postponed', 'Maximum number of seconds that an entry has been in error'] AS descriptions,
  ['gauge', 'gauge', 'gauge'] AS types,
  arrayJoin(arrayZip(names, values, descriptions, types)) AS tpl
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
