-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the dev/ai_events node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.ai_events (
  uuid UUID,
  event LowCardinality(String),
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  person_id UUID,
  properties String,
  retention_days Int16 DEFAULT 30,
  drop_date Date MATERIALIZED toDate(timestamp) + toIntervalDay(retention_days),
  trace_id String,
  session_id Nullable(String),
  parent_id Nullable(String),
  span_id Nullable(String),
  span_type LowCardinality(Nullable(String)),
  generation_id Nullable(String),
  experiment_id Nullable(String),
  span_name Nullable(String),
  trace_name Nullable(String),
  prompt_name Nullable(String),
  model LowCardinality(Nullable(String)),
  provider LowCardinality(Nullable(String)),
  framework LowCardinality(Nullable(String)),
  total_tokens Nullable(Int64),
  input_tokens Nullable(Int64),
  output_tokens Nullable(Int64),
  text_input_tokens Nullable(Int64),
  text_output_tokens Nullable(Int64),
  image_input_tokens Nullable(Int64),
  image_output_tokens Nullable(Int64),
  audio_input_tokens Nullable(Int64),
  audio_output_tokens Nullable(Int64),
  video_input_tokens Nullable(Int64),
  video_output_tokens Nullable(Int64),
  reasoning_tokens Nullable(Int64),
  cache_read_input_tokens Nullable(Int64),
  cache_creation_input_tokens Nullable(Int64),
  web_search_count Nullable(Int64),
  input_cost_usd Nullable(Float64),
  output_cost_usd Nullable(Float64),
  total_cost_usd Nullable(Float64),
  request_cost_usd Nullable(Float64),
  web_search_cost_usd Nullable(Float64),
  audio_cost_usd Nullable(Float64),
  image_cost_usd Nullable(Float64),
  video_cost_usd Nullable(Float64),
  latency Nullable(Float64),
  time_to_first_token Nullable(Float64),
  is_error UInt8,
  error Nullable(String),
  error_type LowCardinality(Nullable(String)),
  error_normalized Nullable(String),
  input Nullable(String),
  output Nullable(String),
  output_choices Nullable(String),
  input_state Nullable(String),
  output_state Nullable(String),
  tools Nullable(String),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64,
  INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
  INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_parent_id parent_id TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_span_id span_id TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_prompt_name prompt_name TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_model model TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_experiment_id experiment_id TYPE bloom_filter(0.01) GRANULARITY 1,
  INDEX idx_event event TYPE set(20) GRANULARITY 1,
  INDEX idx_is_error is_error TYPE set(2) GRANULARITY 1,
  INDEX idx_provider provider TYPE set(50) GRANULARITY 1
) ENGINE = ReplicatedMergeTree('/clickhouse/ai_events/tables/{shard}/posthog.ai_events', '{replica}') ORDER BY (team_id, trace_id, timestamp) PARTITION BY toYYYYMM(drop_date) TTL drop_date SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
CREATE TABLE posthog.kafka_ai_events_json_ws (
  uuid UUID,
  event String,
  properties String,
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  elements_chain String,
  created_at DateTime64(6, 'UTC'),
  person_id UUID,
  person_properties String,
  person_created_at DateTime64(3),
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)
) ENGINE = Kafka(warpstream_ingestion) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_ai_events_ws', kafka_max_block_size = 5000, kafka_num_consumers = 1, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_ai_events_json';
CREATE TABLE posthog.person (
  id UUID,
  created_at DateTime64(3),
  team_id Int64,
  properties String,
  is_identified Int8,
  is_deleted Int8,
  version UInt64,
  last_seen_at Nullable(DateTime64(3))
) ENGINE = Distributed('posthog', 'posthog', 'person');
CREATE TABLE posthog.person_distinct_id2 (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64
) ENGINE = Distributed('posthog', 'posthog', 'person_distinct_id2');
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
CREATE MATERIALIZED VIEW posthog.ai_events_json_ws_mv TO posthog.ai_events (uuid UUID, event String, timestamp DateTime64(6, 'UTC'), team_id Int64, distinct_id String, person_id UUID, properties String, trace_id String, session_id Nullable(String), parent_id Nullable(String), span_id Nullable(String), span_type Nullable(String), generation_id Nullable(String), experiment_id Nullable(String), span_name Nullable(String), trace_name Nullable(String), prompt_name Nullable(String), model Nullable(String), provider Nullable(String), framework Nullable(String), total_tokens Nullable(Int64), input_tokens Nullable(Int64), output_tokens Nullable(Int64), text_input_tokens Nullable(Int64), text_output_tokens Nullable(Int64), image_input_tokens Nullable(Int64), image_output_tokens Nullable(Int64), audio_input_tokens Nullable(Int64), audio_output_tokens Nullable(Int64), video_input_tokens Nullable(Int64), video_output_tokens Nullable(Int64), reasoning_tokens Nullable(Int64), cache_read_input_tokens Nullable(Int64), cache_creation_input_tokens Nullable(Int64), web_search_count Nullable(Int64), input_cost_usd Nullable(Float64), output_cost_usd Nullable(Float64), total_cost_usd Nullable(Float64), request_cost_usd Nullable(Float64), web_search_cost_usd Nullable(Float64), audio_cost_usd Nullable(Float64), image_cost_usd Nullable(Float64), video_cost_usd Nullable(Float64), latency Nullable(Float64), time_to_first_token Nullable(Float64), is_error UInt8, error Nullable(String), error_type Nullable(String), error_normalized Nullable(String), input Nullable(String), output Nullable(String), output_choices Nullable(String), input_state Nullable(String), output_state Nullable(String), tools Nullable(String), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  uuid,
  event,
  timestamp,
  team_id,
  distinct_id,
  person_id,
  concat(
    '{',
    arrayStringConcat(
      arrayMap(
        x -> concat('"', x.1, '":', x.2),
        arrayFilter(
          x -> ((x.1) NOT IN ('$ai_input', '$ai_output', '$ai_output_choices', '$ai_input_state', '$ai_output_state', '$ai_tools')),
          JSONExtractKeysAndValuesRaw(src.properties)
        )
      ),
      ','
    ),
    '}'
  ) AS properties,
  JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
  JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
  JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
  JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
  JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
  JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
  JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,
  JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
  JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
  JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,
  JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
  JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
  JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,
  JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
  JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
  JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
  JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
  JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
  JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
  JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
  JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
  JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
  JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
  JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
  JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
  JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
  JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
  JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,
  JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
  JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
  JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
  JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
  JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
  JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
  JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
  JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,
  JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
  JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,
  if((JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"')), 1, 0) AS is_error,
  JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
  JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
  JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,
  nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
  nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
  nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
  nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_ai_events_json_ws AS src;
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
