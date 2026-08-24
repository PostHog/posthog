-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the local-multi/small node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.kafka_app_metrics (
  team_id Int64,
  timestamp DateTime64(6, 'UTC'),
  plugin_config_id Int64,
  category LowCardinality(String),
  job_id String,
  successes Int64,
  successes_on_retry Int64,
  failures Int64,
  error_uuid UUID,
  error_type String,
  error_details String CODEC(ZSTD(3))
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_app_metrics\'';
CREATE TABLE posthog.kafka_billing_usage_records (
  schema_version UInt8,
  record_id String,
  producer_id LowCardinality(String),
  team_id Int64,
  organization_id UUID,
  usage_key LowCardinality(String),
  unit LowCardinality(String),
  quantity Int64,
  timestamp DateTime64(6, 'UTC'),
  inserted_at DateTime64(6, 'UTC')
) ENGINE = Kafka() SETTINGS date_time_input_format = 'best_effort', kafka_broker_list = 'warpstream_ingestion', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_billing_usage_records\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_billing_usage_records\'';
CREATE TABLE posthog.kafka_duplicate_events (
  team_id Int64,
  distinct_id String,
  event String,
  source_uuid UUID,
  duplicate_uuid UUID,
  similarity_score Float64,
  dedup_type LowCardinality(String),
  is_confirmed UInt8,
  reason Nullable(String),
  version String,
  different_property_count UInt32,
  properties_similarity Float64,
  source_message String,
  duplicate_message String,
  distinct_fields String,
  inserted_at DateTime64(3, 'UTC')
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_duplicate_events\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_ingestion_events_duplicates\'';
CREATE TABLE posthog.kafka_error_tracking_issue_fingerprint_embeddings (
  team_id Int64,
  model_name LowCardinality(String),
  embedding_version Int64,
  fingerprint String,
  inserted_at DateTime64(3, 'UTC'),
  embeddings Array(Float64)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_error_tracking_fingerprint_embeddings\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_error_tracking_issue_fingerprint_embeddings\'';
CREATE TABLE posthog.kafka_error_tracking_issue_fingerprint_overrides (
  team_id Int64,
  fingerprint String,
  issue_id UUID,
  is_deleted Int8,
  version Int64
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse-error-tracking-issue-fingerprint-overrides\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_error_tracking_issue_fingerprint\'';
CREATE TABLE posthog.kafka_events_dead_letter_queue (
  id UUID,
  event_uuid UUID,
  event String,
  properties String,
  distinct_id String,
  team_id Int64,
  elements_chain String,
  created_at DateTime64(6, 'UTC'),
  ip String,
  site_url String,
  now DateTime64(6, 'UTC'),
  raw_payload String,
  error_timestamp DateTime64(6, 'UTC'),
  error_location String,
  error String,
  tags Array(String)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_skip_broken_messages = 1000, kafka_topic_list = 'kafka_topic_list = \'events_dead_letter_queue\'';
CREATE TABLE posthog.kafka_groups (
  group_type_index UInt8,
  group_key String,
  created_at DateTime64(3),
  team_id Int64,
  group_properties String
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_groups\'';
CREATE TABLE posthog.kafka_ingestion_warnings (
  team_id Int64,
  source LowCardinality(String),
  type String,
  details String CODEC(ZSTD(3)),
  timestamp DateTime64(6, 'UTC')
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_ingestion_warnings\'';
CREATE TABLE posthog.kafka_log_entries_v3 (
  team_id UInt64,
  log_source LowCardinality(String),
  log_source_id String,
  instance_id String,
  timestamp DateTime64(6, 'UTC'),
  level LowCardinality(String),
  message String
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_log_entries\'', kafka_skip_broken_messages = 100, kafka_topic_list = 'kafka_topic_list = \'log_entries\'';
CREATE TABLE posthog.kafka_log_entries_ws (
  team_id UInt64,
  log_source LowCardinality(String),
  log_source_id String,
  instance_id String,
  timestamp DateTime64(6, 'UTC'),
  level LowCardinality(String),
  message String
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_ingestion', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_log_entries_ws\'', kafka_skip_broken_messages = 100, kafka_topic_list = 'kafka_topic_list = \'log_entries\'';
CREATE TABLE posthog.kafka_person (
  id UUID,
  created_at DateTime64(3),
  team_id Int64,
  properties String,
  is_identified Int8,
  is_deleted Int8,
  version UInt64,
  last_seen_at Nullable(DateTime64(3))
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_person\'';
CREATE TABLE posthog.kafka_person_distinct_id2 (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_person_distinct_id\'';
CREATE TABLE posthog.kafka_person_distinct_id_overrides (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse-person-distinct-id-overrides\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_person_distinct_id\'';
CREATE TABLE posthog.kafka_plugin_log_entries (
  id UUID,
  team_id Int64,
  plugin_id Int64,
  plugin_config_id Int64,
  timestamp DateTime64(6, 'UTC'),
  source String,
  type String,
  message String,
  instance_id UUID
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'plugin_log_entries\'';
CREATE TABLE posthog.kafka_posthog_document_embeddings (
  team_id Int64,
  product LowCardinality(String),
  document_type LowCardinality(String),
  model_name LowCardinality(String),
  rendering LowCardinality(String),
  document_id String,
  timestamp DateTime64(3, 'UTC'),
  inserted_at DateTime64(3, 'UTC'),
  content String,
  metadata String,
  embedding Array(Float64)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_document_embeddings\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_document_embeddings\'';
CREATE TABLE posthog.kafka_session_replay_events (
  session_id String,
  team_id Int64,
  distinct_id String,
  first_timestamp DateTime64(6, 'UTC'),
  last_timestamp DateTime64(6, 'UTC'),
  block_url Nullable(String),
  first_url Nullable(String),
  urls Array(String),
  click_count Int64,
  keypress_count Int64,
  mouse_activity_count Int64,
  active_milliseconds Int64,
  console_log_count Int64,
  console_warn_count Int64,
  console_error_count Int64,
  size Int64,
  event_count Int64,
  message_count Int64,
  snapshot_source LowCardinality(Nullable(String)),
  snapshot_library Nullable(String),
  retention_period_days Nullable(Int64),
  is_deleted UInt8,
  ai_tags_fixed Array(String),
  ai_tags_freeform Array(String),
  ai_highlighted UInt8,
  surfacing_score Nullable(Float32)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'msk_cluster', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'group1\'', kafka_topic_list = 'kafka_topic_list = \'clickhouse_session_replay_events\'';
CREATE TABLE posthog.kafka_usage_report_events_preagg (
  uuid UUID,
  event String,
  properties String CODEC(ZSTD(3)),
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)
) ENGINE = Kafka() SETTINGS kafka_broker_list = 'warpstream_ingestion', kafka_format = 'kafka_format = \'JSONEachRow\'', kafka_group_name = 'kafka_group_name = \'clickhouse_usage_report_events_preagg\'', kafka_num_consumers = 1, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'kafka_topic_list = \'clickhouse_events_json\'';
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
CREATE TABLE posthog.writable_app_metrics (
  team_id Int64,
  timestamp DateTime64(6, 'UTC'),
  plugin_config_id Int64,
  category LowCardinality(String),
  job_id String,
  successes SimpleAggregateFunction(sum, Int64),
  successes_on_retry SimpleAggregateFunction(sum, Int64),
  failures SimpleAggregateFunction(sum, Int64),
  error_uuid UUID,
  error_type String,
  error_details String CODEC(ZSTD(3)),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_app_metrics', rand());
CREATE TABLE posthog.writable_billing_usage_records (
  schema_version UInt8,
  record_id String,
  producer_id LowCardinality(String),
  team_id Int64,
  organization_id UUID,
  usage_key LowCardinality(String),
  unit LowCardinality(String),
  quantity Int64,
  timestamp DateTime64(6, 'UTC'),
  inserted_at DateTime64(6, 'UTC'),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_billing_usage_records', cityHash64(team_id));
CREATE TABLE posthog.writable_duplicate_events (
  team_id Int64,
  distinct_id String,
  event String,
  source_uuid UUID,
  duplicate_uuid UUID,
  similarity_score Float64,
  dedup_type LowCardinality(String),
  is_confirmed UInt8,
  reason Nullable(String),
  version String,
  different_property_count UInt32,
  properties_similarity Float64,
  source_message String,
  duplicate_message String,
  distinct_fields Array(Tuple(field_name String, original_value String, new_value String)),
  inserted_at DateTime64(3, 'UTC'),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'duplicate_events');
CREATE TABLE posthog.writable_error_tracking_issue_fingerprint_embeddings (
  team_id Int64,
  model_name LowCardinality(String),
  embedding_version Int64,
  fingerprint String,
  inserted_at DateTime64(3, 'UTC'),
  embeddings Array(Float64),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'error_tracking_issue_fingerprint_embeddings');
CREATE TABLE posthog.writable_error_tracking_issue_fingerprint_overrides (
  team_id Int64,
  fingerprint String,
  issue_id UUID,
  is_deleted Int8,
  version Int64,
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'error_tracking_issue_fingerprint_overrides');
CREATE TABLE posthog.writable_events_dead_letter_queue (
  id UUID,
  event_uuid UUID,
  event String,
  properties String,
  distinct_id String,
  team_id Int64,
  elements_chain String,
  created_at DateTime64(6, 'UTC'),
  ip String,
  site_url String,
  now DateTime64(6, 'UTC'),
  raw_payload String,
  error_timestamp DateTime64(6, 'UTC'),
  error_location String,
  error String,
  tags Array(String),
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'events_dead_letter_queue');
CREATE TABLE posthog.writable_groups (
  group_type_index UInt8,
  group_key String,
  created_at DateTime64(3),
  team_id Int64,
  group_properties String,
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'groups');
CREATE TABLE posthog.writable_ingestion_warnings (
  team_id Int64,
  source LowCardinality(String),
  type String,
  details String CODEC(ZSTD(3)),
  timestamp DateTime64(6, 'UTC'),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_ingestion_warnings', rand());
CREATE TABLE posthog.writable_log_entries (
  team_id UInt64,
  log_source LowCardinality(String),
  log_source_id String,
  instance_id String,
  timestamp DateTime64(6, 'UTC'),
  level LowCardinality(String),
  message String,
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_log_entries', rand());
CREATE TABLE posthog.writable_person (
  id UUID,
  created_at DateTime64(3),
  team_id Int64,
  properties String,
  is_identified Int8,
  is_deleted Int8,
  version UInt64,
  last_seen_at Nullable(DateTime64(3)),
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'person');
CREATE TABLE posthog.writable_person_distinct_id2 (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64,
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'person_distinct_id2');
CREATE TABLE posthog.writable_person_distinct_id_overrides (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  is_deleted Int8,
  version Int64,
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'person_distinct_id_overrides');
CREATE TABLE posthog.writable_plugin_log_entries (
  id UUID,
  team_id Int64,
  plugin_id Int64,
  plugin_config_id Int64,
  timestamp DateTime64(6, 'UTC'),
  source String,
  type String,
  message String,
  instance_id UUID,
  _timestamp DateTime,
  _offset UInt64
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'plugin_log_entries');
CREATE TABLE posthog.writable_posthog_document_embeddings (
  team_id Int64,
  product LowCardinality(String),
  document_type LowCardinality(String),
  model_name LowCardinality(String),
  rendering LowCardinality(String),
  document_id String,
  timestamp DateTime64(3, 'UTC'),
  inserted_at DateTime64(3, 'UTC'),
  content String DEFAULT '',
  metadata String DEFAULT '{}',
  embedding Array(Float64),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'partitioned_sharded_posthog_document_embeddings', cityHash64(document_id));
CREATE TABLE posthog.writable_posthog_document_embeddings_buffer (
  team_id Int64,
  product LowCardinality(String),
  document_type LowCardinality(String),
  model_name LowCardinality(String),
  rendering LowCardinality(String),
  document_id String,
  timestamp DateTime64(3, 'UTC'),
  inserted_at DateTime64(3, 'UTC'),
  content String DEFAULT '',
  metadata String DEFAULT '{}',
  embedding Array(Float64),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_posthog_document_embeddings_buffer', cityHash64(document_id));
CREATE TABLE posthog.writable_session_replay_events (
  session_id String,
  team_id Int64,
  distinct_id String,
  min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
  max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
  block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
  block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
  block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
  first_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  click_count SimpleAggregateFunction(sum, Int64),
  keypress_count SimpleAggregateFunction(sum, Int64),
  mouse_activity_count SimpleAggregateFunction(sum, Int64),
  active_milliseconds SimpleAggregateFunction(sum, Int64),
  console_log_count SimpleAggregateFunction(sum, Int64),
  console_warn_count SimpleAggregateFunction(sum, Int64),
  console_error_count SimpleAggregateFunction(sum, Int64),
  size SimpleAggregateFunction(sum, Int64),
  message_count SimpleAggregateFunction(sum, Int64),
  event_count SimpleAggregateFunction(sum, Int64),
  snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
  snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
  _timestamp SimpleAggregateFunction(max, DateTime),
  retention_period_days SimpleAggregateFunction(max, Nullable(Int64)),
  is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
  ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
  ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0,
  surfacing_score SimpleAggregateFunction(max, Nullable(Float32))
) ENGINE = Distributed('posthog', 'posthog', 'sharded_session_replay_events', sipHash64(distinct_id));
CREATE TABLE posthog.writable_usage_report_events_preagg (
  date Date,
  team_id Int64,
  person_mode LowCardinality(String),
  lib LowCardinality(String),
  event String,
  distinct_events_unique AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64)),
  event_count AggregateFunction(sum, UInt64)
) ENGINE = Distributed('aux', 'posthog', 'sharded_usage_report_events_preagg', sipHash64(date));
CREATE MATERIALIZED VIEW posthog.app_metrics_mv TO posthog.writable_app_metrics (team_id Int64, timestamp DateTime64(6, 'UTC'), plugin_config_id Int64, category LowCardinality(String), job_id String, successes Int64, successes_on_retry Int64, failures Int64, error_uuid UUID, error_type String, error_details String, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  timestamp,
  plugin_config_id,
  category,
  job_id,
  successes,
  successes_on_retry,
  failures,
  error_uuid,
  error_type,
  error_details,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics;
CREATE MATERIALIZED VIEW posthog.billing_usage_records_mv TO posthog.writable_billing_usage_records (schema_version UInt8, record_id String, producer_id LowCardinality(String), team_id Int64, organization_id UUID, usage_key LowCardinality(String), unit LowCardinality(String), quantity Int64, timestamp DateTime64(6, 'UTC'), inserted_at DateTime64(6, 'UTC'), _timestamp DateTime, _offset UInt64, _partition UInt64) AS SELECT
  schema_version,
  record_id,
  producer_id,
  team_id,
  organization_id,
  usage_key,
  unit,
  quantity,
  timestamp,
  inserted_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_billing_usage_records;
CREATE MATERIALIZED VIEW posthog.duplicate_events_mv TO posthog.writable_duplicate_events (team_id Int64, distinct_id String, event String, source_uuid UUID, duplicate_uuid UUID, similarity_score Float64, dedup_type LowCardinality(String), is_confirmed UInt8, reason Nullable(String), version String, different_property_count UInt32, properties_similarity Float64, source_message String, duplicate_message String, distinct_fields Array(Tuple(field_name String, original_value String, new_value String)), inserted_at DateTime64(3, 'UTC'), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  distinct_id,
  event,
  source_uuid,
  duplicate_uuid,
  similarity_score,
  dedup_type,
  is_confirmed,
  reason,
  version,
  different_property_count,
  properties_similarity,
  source_message,
  duplicate_message,
  JSONExtract(
    distinct_fields,
    'Array(Tuple(field_name String, original_value String, new_value String))'
  ) AS distinct_fields,
  inserted_at,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_duplicate_events;
CREATE MATERIALIZED VIEW posthog.error_tracking_issue_fingerprint_embeddings_mv TO posthog.writable_error_tracking_issue_fingerprint_embeddings (team_id Int64, model_name LowCardinality(String), embedding_version Int64, fingerprint String, inserted_at Nullable(DateTime), embeddings Array(Float64), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  model_name,
  embedding_version,
  fingerprint,
  _timestamp AS inserted_at,
  embeddings,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_issue_fingerprint_embeddings;
CREATE MATERIALIZED VIEW posthog.error_tracking_issue_fingerprint_overrides_mv TO posthog.writable_error_tracking_issue_fingerprint_overrides (team_id Int64, fingerprint String, issue_id UUID, is_deleted Int8, version Int64, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  fingerprint,
  issue_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_error_tracking_issue_fingerprint_overrides
WHERE version > 0;
CREATE MATERIALIZED VIEW posthog.events_dead_letter_queue_mv TO posthog.writable_events_dead_letter_queue (id UUID, event_uuid UUID, event String, properties String, distinct_id String, team_id Int64, elements_chain String, created_at DateTime64(6, 'UTC'), ip String, site_url String, now DateTime64(6, 'UTC'), raw_payload String, error_timestamp DateTime64(6, 'UTC'), error_location String, error String, tags Array(String), _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  id,
  event_uuid,
  event,
  properties,
  distinct_id,
  team_id,
  elements_chain,
  created_at,
  ip,
  site_url,
  now,
  raw_payload,
  error_timestamp,
  error_location,
  error,
  tags,
  _timestamp,
  _offset
FROM posthog.kafka_events_dead_letter_queue;
CREATE MATERIALIZED VIEW posthog.groups_mv TO posthog.writable_groups (group_type_index UInt8, group_key String, created_at DateTime64(3), team_id Int64, group_properties String, _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  group_type_index,
  group_key,
  created_at,
  team_id,
  group_properties,
  _timestamp,
  _offset
FROM posthog.kafka_groups;
CREATE MATERIALIZED VIEW posthog.ingestion_warnings_mv TO posthog.writable_ingestion_warnings (team_id Int64, source LowCardinality(String), type String, details String, timestamp DateTime64(6, 'UTC'), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  source,
  type,
  details,
  timestamp,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_ingestion_warnings;
CREATE MATERIALIZED VIEW posthog.log_entries_v3_mv TO posthog.writable_log_entries (team_id UInt64, log_source LowCardinality(String), log_source_id String, instance_id String, timestamp DateTime64(6, 'UTC'), level LowCardinality(String), message String, _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  team_id,
  log_source,
  log_source_id,
  instance_id,
  timestamp,
  level,
  message,
  _timestamp,
  _offset
FROM posthog.kafka_log_entries_v3
WHERE toDate(timestamp) <= today();
CREATE MATERIALIZED VIEW posthog.log_entries_ws_mv TO posthog.writable_log_entries (team_id UInt64, log_source LowCardinality(String), log_source_id String, instance_id String, timestamp DateTime64(6, 'UTC'), level LowCardinality(String), message String, _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  team_id,
  log_source,
  log_source_id,
  instance_id,
  timestamp,
  level,
  message,
  _timestamp,
  _offset
FROM posthog.kafka_log_entries_ws
WHERE toDate(timestamp) <= today();
CREATE MATERIALIZED VIEW posthog.person_distinct_id2_mv TO posthog.writable_person_distinct_id2 (team_id Int64, distinct_id String, person_id UUID, is_deleted Int8, version Int64, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  distinct_id,
  person_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_person_distinct_id2;
CREATE MATERIALIZED VIEW posthog.person_distinct_id_overrides_mv TO posthog.writable_person_distinct_id_overrides (team_id Int64, distinct_id String, person_id UUID, is_deleted Int8, version Int64, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  distinct_id,
  person_id,
  is_deleted,
  version,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_person_distinct_id_overrides
WHERE version > 0;
CREATE MATERIALIZED VIEW posthog.person_mv TO posthog.writable_person (id UUID, created_at DateTime64(3), team_id Int64, properties String, is_identified Int8, is_deleted Int8, version UInt64, last_seen_at Nullable(DateTime64(3)), _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  id,
  created_at,
  team_id,
  properties,
  is_identified,
  is_deleted,
  version,
  last_seen_at,
  _timestamp,
  _offset
FROM posthog.kafka_person;
CREATE MATERIALIZED VIEW posthog.plugin_log_entries_mv TO posthog.writable_plugin_log_entries (id UUID, team_id Int64, plugin_id Int64, plugin_config_id Int64, timestamp DateTime64(6, 'UTC'), source String, type String, message String, instance_id UUID, _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  id,
  team_id,
  plugin_id,
  plugin_config_id,
  timestamp,
  source,
  type,
  message,
  instance_id,
  _timestamp,
  _offset
FROM posthog.kafka_plugin_log_entries;
CREATE MATERIALIZED VIEW posthog.posthog_document_embeddings_kafka_to_buffer_mv TO posthog.writable_posthog_document_embeddings_buffer (team_id Int64, product LowCardinality(String), document_type LowCardinality(String), model_name LowCardinality(String), rendering LowCardinality(String), document_id String, timestamp DateTime64(3, 'UTC'), inserted_at Nullable(DateTime), content String, metadata String, embedding Array(Float64), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  product,
  document_type,
  model_name,
  rendering,
  document_id,
  timestamp,
  _timestamp AS inserted_at,
  coalesce(content, '') AS content,
  coalesce(metadata, '{}') AS metadata,
  embedding,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_posthog_document_embeddings;
CREATE MATERIALIZED VIEW posthog.session_replay_events_mv TO posthog.writable_session_replay_events (session_id String, team_id Int64, distinct_id String, min_first_timestamp DateTime64(6, 'UTC'), max_last_timestamp DateTime64(6, 'UTC'), block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))), block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))), block_urls SimpleAggregateFunction(groupArrayArray, Array(String)), first_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')), all_urls SimpleAggregateFunction(groupUniqArrayArray, Array(String)), click_count Int64, keypress_count Int64, mouse_activity_count Int64, active_milliseconds Int64, console_log_count Int64, console_warn_count Int64, console_error_count Int64, size Int64, message_count Int64, event_count Int64, snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')), snapshot_library AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')), _timestamp Nullable(DateTime), retention_period_days SimpleAggregateFunction(max, Nullable(Int64)), is_deleted SimpleAggregateFunction(max, UInt8), ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)), ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)), ai_highlighted SimpleAggregateFunction(max, UInt8), surfacing_score SimpleAggregateFunction(max, Nullable(Float32))) AS SELECT
  session_id,
  team_id,
  any(distinct_id) AS distinct_id,
  min(first_timestamp) AS min_first_timestamp,
  max(last_timestamp) AS max_last_timestamp,
  groupArray(if(block_url != '', first_timestamp, NULL)) AS block_first_timestamps,
  groupArray(if(block_url != '', last_timestamp, NULL)) AS block_last_timestamps,
  groupArray(block_url) AS block_urls,
  argMinState(first_url, first_timestamp) AS first_url,
  groupUniqArrayArray(urls) AS all_urls,
  sum(click_count) AS click_count,
  sum(keypress_count) AS keypress_count,
  sum(mouse_activity_count) AS mouse_activity_count,
  sum(active_milliseconds) AS active_milliseconds,
  sum(console_log_count) AS console_log_count,
  sum(console_warn_count) AS console_warn_count,
  sum(console_error_count) AS console_error_count,
  sum(size) AS size,
  sum(message_count) AS message_count,
  sum(event_count) AS event_count,
  argMinState(snapshot_source, first_timestamp) AS snapshot_source,
  argMinState(snapshot_library, first_timestamp) AS snapshot_library,
  max(_timestamp) AS _timestamp,
  max(retention_period_days) AS retention_period_days,
  max(is_deleted) AS is_deleted,
  groupUniqArrayArray(ai_tags_fixed) AS ai_tags_fixed,
  groupUniqArrayArray(ai_tags_freeform) AS ai_tags_freeform,
  max(ai_highlighted) AS ai_highlighted,
  max(surfacing_score) AS surfacing_score
FROM posthog.kafka_session_replay_events
GROUP BY
  session_id, team_id;
CREATE MATERIALIZED VIEW posthog.usage_report_events_preagg_mv TO posthog.writable_usage_report_events_preagg (date Date, team_id Int64, person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2), lib String, event String, distinct_events_unique AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64)), event_count AggregateFunction(sum, UInt64)) AS SELECT
  toDate(timestamp) AS date,
  team_id,
  person_mode,
  JSONExtractString(properties, '$lib') AS lib,
  event,
  uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
  sumState(toUInt64(1)) AS event_count
FROM posthog.kafka_usage_report_events_preagg
GROUP BY
  date, team_id, person_mode, lib, event;
