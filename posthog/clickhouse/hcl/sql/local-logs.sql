-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the local/logs node. Apply to a fresh ClickHouse to build it.

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
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_logs', kafka_format = 'kafka_format = \'Avro\'', kafka_group_name = 'kafka_group_name = \'clickhouse-logs-avro-new\'', kafka_num_consumers = 8, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_logs\'';
CREATE TABLE posthog.log_attributes (
  team_id Int32 CODEC(DoubleDelta, ZSTD(1)),
  time_bucket DateTime64(0) CODEC(DoubleDelta, ZSTD(1)),
  original_expiry_time_bucket DateTime64(0) CODEC(DoubleDelta, ZSTD(1)),
  service_name LowCardinality(String) CODEC(ZSTD(1)),
  resource_fingerprint UInt64 DEFAULT 0 CODEC(DoubleDelta, ZSTD(1)),
  attribute_key LowCardinality(String) CODEC(ZSTD(1)),
  attribute_value String CODEC(ZSTD(1)),
  attribute_count SimpleAggregateFunction(sum, UInt64),
  attribute_type LowCardinality(String),
  INDEX idx_attribute_key attribute_key TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_value attribute_value TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attribute_key_n3 attribute_key TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1,
  INDEX idx_attribute_value_n3 attribute_value TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(original_expiry_time_bucket) SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192, storage_policy = 'default';
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
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes2', '{replica}-{shard}') ORDER BY (team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value) PARTITION BY toDate(original_expiry_time_bucket) TTL original_expiry_time_bucket SETTINGS deduplicate_merge_projection_mode = 'drop', index_granularity = 8192;
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
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'log_attributes2');
CREATE TABLE posthog.logs32 (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
  original_expiry_timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  uuid String CODEC(ZSTD(1)),
  team_id Int32 CODEC(ZSTD(1)),
  trace_id String CODEC(ZSTD(1)),
  span_id String CODEC(ZSTD(1)),
  trace_flags Int32 CODEC(ZSTD(1)),
  timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  observed_timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  created_at DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
  body String CODEC(ZSTD(1)),
  severity_text LowCardinality(String) CODEC(ZSTD(1)),
  severity_number Int32 CODEC(ZSTD(1)),
  service_name LowCardinality(String) CODEC(ZSTD(1)),
  resource_attributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
  instrumentation_scope String CODEC(ZSTD(1)),
  event_name String CODEC(ZSTD(1)),
  attributes_map_str Map(LowCardinality(String), String) CODEC(ZSTD(1)),
  level String ALIAS severity_text,
  mat_body_ipv4_matches Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\.)(2, 2)([0-9]))'),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)) CODEC(ZSTD(1)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)) CODEC(ZSTD(1)),
  _partition UInt32 CODEC(DoubleDelta, ZSTD(1)),
  _topic String,
  _offset UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _bytes_uncompressed UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _bytes_compressed UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _record_count UInt64 CODEC(DoubleDelta, ZSTD(1)),
  INDEX idx_severity_text_set severity_text TYPE set(10) GRANULARITY 1,
  INDEX idx_attributes_str_keys mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attributes_str_values mapValues(attributes_map_str) TYPE bloom_filter(0.001) GRANULARITY 1,
  INDEX idx_mat_body_ipv4_matches mat_body_ipv4_matches TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_body_ngram3 lower(body) TYPE ngrambf_v1(3, 25000, 2, 0) GRANULARITY 1,
  INDEX idx_uuid_bloom uuid TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_observed_minmax observed_timestamp TYPE minmax GRANULARITY 1,
  INDEX idx_timestamp_minmax timestamp TYPE minmax GRANULARITY 1
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.logs32', '{replica}-{shard}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp) PARTITION BY toDate(original_expiry_timestamp) SETTINGS add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, allow_remote_fs_zero_copy_replication = 1, index_granularity = 8192, index_granularity_bytes = 104857600, storage_policy = 'default', ttl_only_drop_parts = 1;
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
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.logs34', '{replica}-{shard}') ORDER BY (team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp) PARTITION BY toDate(original_expiry_timestamp) TTL original_expiry_timestamp SETTINGS add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1;
CREATE TABLE posthog.logs_billing_metrics (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  bytes_uncompressed SimpleAggregateFunction(sum, UInt64),
  bytes_compressed SimpleAggregateFunction(sum, UInt64),
  record_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_billing_metrics', '{replica}-{shard}') ORDER BY (team_id, time_bucket, service_name) PARTITION BY toYYYYMM(time_bucket) SETTINGS deduplicate_merge_projection_mode = 'rebuild', index_granularity = 8192;
CREATE TABLE posthog.logs_billing_metrics_distributed (
  team_id Int32,
  time_bucket DateTime64(0),
  service_name LowCardinality(String),
  bytes_uncompressed SimpleAggregateFunction(sum, UInt64),
  bytes_compressed SimpleAggregateFunction(sum, UInt64),
  record_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'logs_billing_metrics');
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
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'logs34');
CREATE TABLE posthog.logs_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_kafka_metrics', '{replica}-{shard}') ORDER BY (_topic, _partition) SETTINGS index_granularity = 8192;
CREATE TABLE posthog.logs_kafka_metrics_distributed (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'logs_kafka_metrics');
CREATE TABLE posthog.metric_samples1 (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  timestamp DateTime64(6) CODEC(DoubleDelta),
  value Float64 CODEC(Gorilla(8)),
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
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6) CODEC(DoubleDelta),
  INDEX idx_service_set service_name TYPE set(1000) GRANULARITY 1,
  INDEX idx_attr_keys mapKeys(attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_attr_values mapValues(attributes) TYPE bloom_filter(0.01) GRANULARITY 1
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series1', '{replica}-{shard}', last_seen) ORDER BY (team_id, metric_name, series_fingerprint) SETTINGS index_granularity = 8192;
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
CREATE MATERIALIZED VIEW posthog.kafka_logs34_avro_mv TO posthog.logs34 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), body String, severity_text String, severity_number Int32, service_name String, instrumentation_scope String, event_name String, attributes_map_str Map(String, String), resource_attributes Map(String, String), team_id Int32, original_expiry_timestamp DateTime64(6), _partition UInt64, _topic LowCardinality(String), _offset UInt64, _record_count Int64, _bytes_uncompressed Nullable(Int64), _bytes_compressed Nullable(Int64)) AS SELECT
  kafka_logs_avro.* EXCEPT(created_at, attribute_values, attribute_keys, attributes, attributes_map_str, attributes_map_float, attributes_map_datetime, resource_attributes, bytes_uncompressed),
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
CREATE MATERIALIZED VIEW posthog.logs32_to_log_attributes TO posthog.log_attributes (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, attributes
  );
CREATE MATERIALIZED VIEW posthog.logs32_to_resource_attributes TO posthog.log_attributes (team_id Int32, time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), resource_fingerprint UInt64, attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
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
    FROM posthog.logs32
    GROUP BY
      team_id, time_bucket, original_expiry_time_bucket, service_name, resource_fingerprint, resource_attributes
  );
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
CREATE TABLE posthog.logs (
  time_bucket DateTime MATERIALIZED toStartOfDay(timestamp) CODEC(DoubleDelta, ZSTD(1)),
  original_expiry_timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  uuid String CODEC(ZSTD(1)),
  team_id Int32 CODEC(ZSTD(1)),
  trace_id String CODEC(ZSTD(1)),
  span_id String CODEC(ZSTD(1)),
  trace_flags Int32 CODEC(ZSTD(1)),
  timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  observed_timestamp DateTime64(6) CODEC(DoubleDelta, ZSTD(1)),
  created_at DateTime64(6) MATERIALIZED now() CODEC(DoubleDelta, ZSTD(1)),
  body String CODEC(ZSTD(1)),
  severity_text LowCardinality(String) CODEC(ZSTD(1)),
  severity_number Int32 CODEC(ZSTD(1)),
  service_name LowCardinality(String) CODEC(ZSTD(1)),
  resource_attributes Map(LowCardinality(String), String) CODEC(ZSTD(1)),
  resource_fingerprint UInt64 MATERIALIZED cityHash64(resource_attributes) CODEC(DoubleDelta, ZSTD(1)),
  instrumentation_scope String CODEC(ZSTD(1)),
  event_name String CODEC(ZSTD(1)),
  attributes_map_str Map(LowCardinality(String), String) CODEC(ZSTD(1)),
  level String ALIAS severity_text,
  mat_body_ipv4_matches Array(String) ALIAS extractAll(body, '(\\d\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\.)(2, 2)([0-9]))'),
  time_minute DateTime ALIAS toStartOfMinute(timestamp),
  attributes Map(LowCardinality(String), String) ALIAS mapApply((k, v) -> (left(k, -5), v), attributes_map_str),
  attributes_map_float Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str)) CODEC(ZSTD(1)),
  attributes_map_datetime Map(LowCardinality(String), DateTime64(6)) MATERIALIZED mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str)) CODEC(ZSTD(1)),
  _partition UInt32 CODEC(DoubleDelta, ZSTD(1)),
  _topic String,
  _offset UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _bytes_uncompressed UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _bytes_compressed UInt64 CODEC(DoubleDelta, ZSTD(1)),
  _record_count UInt64 CODEC(DoubleDelta, ZSTD(1))
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'logs32');
CREATE TABLE posthog.metric_samples (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  timestamp DateTime64(6) CODEC(DoubleDelta),
  value Float64 CODEC(Gorilla(8)),
  trace_id String,
  span_id String,
  trace_flags Int32
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'metric_samples1');
CREATE TABLE posthog.metric_series (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64 CODEC(DoubleDelta),
  metric_type LowCardinality(String),
  unit LowCardinality(String),
  service_name LowCardinality(String),
  resource_attributes Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String),
  last_seen DateTime64(6) CODEC(DoubleDelta)
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'metric_series1');
