-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the prod-eu/ai_events node. Apply to a fresh ClickHouse to build it.

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
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_ingestion', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_ai_events_ws\'', kafka_max_block_size = 5000, kafka_num_consumers = 16, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_ai_events_json\'';
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
