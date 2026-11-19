-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the local-multi/medium node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.kafka_app_metrics2 (
  team_id Int64,
  timestamp DateTime64(6, 'UTC'),
  app_source LowCardinality(String),
  app_source_id String,
  instance_id String,
  metric_kind String,
  metric_name String,
  count Int64
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_app_metrics2';
CREATE TABLE posthog.kafka_app_metrics2_ws (
  team_id Int64,
  timestamp DateTime64(6, 'UTC'),
  app_source LowCardinality(String),
  app_source_id String,
  instance_id String,
  metric_kind String,
  metric_name String,
  count Int64
) ENGINE = Kafka(warpstream_ingestion) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_app_metrics2_ws', kafka_topic_list = 'clickhouse_app_metrics2';
CREATE TABLE posthog.kafka_cohort_membership (
  team_id Int64,
  cohort_id Int64,
  person_id UUID,
  status Enum8('entered'=1, 'left'=2, 'member'=3, 'not_member'=4),
  last_updated DateTime64(6)
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_cohort_membership_changed', kafka_topic_list = 'cohort_membership_changed';
CREATE TABLE posthog.kafka_distinct_id_usage (
  team_id Int64,
  distinct_id String,
  timestamp DateTime64(6, 'UTC')
) ENGINE = Kafka(warpstream_ingestion) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_distinct_id_usage', kafka_skip_broken_messages = 100, kafka_topic_list = 'distinct_id_usage_events_json';
CREATE TABLE posthog.kafka_flag_evaluations (
  uuid UUID,
  event LowCardinality(String),
  properties String,
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  created_at DateTime64(6, 'UTC'),
  person_id UUID,
  person_properties String,
  person_created_at DateTime64(3),
  inserted_at DateTime64(6, 'UTC'),
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)
) ENGINE = Kafka(warpstream_ingestion) SETTINGS kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_flag_evaluations', kafka_max_block_size = 10000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 10000, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_flag_evaluations';
CREATE TABLE posthog.kafka_heatmaps (
  session_id String,
  team_id Int64,
  distinct_id String,
  timestamp DateTime64(6, 'UTC'),
  x Int16,
  y Int16,
  scale_factor Int16,
  viewport_width Int16,
  viewport_height Int16,
  pointer_target_fixed Bool,
  current_url String,
  type LowCardinality(String)
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'clickhouse_heatmap_events';
CREATE TABLE posthog.kafka_precalculated_events (
  team_id Int64,
  date Nullable(Date),
  distinct_id String,
  person_id UUID,
  condition String,
  uuid UUID,
  source String
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_prefiltered_events', kafka_max_block_size = 1000000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_prefiltered_events';
CREATE TABLE posthog.kafka_precalculated_person_properties (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  condition String,
  matches Bool,
  source String
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_flush_interval_ms = 7500, kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_precalculated_person_properties', kafka_max_block_size = 1000000, kafka_num_consumers = 1, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_precalculated_person_properties';
CREATE TABLE posthog.kafka_tophog (
  timestamp DateTime64(6, 'UTC'),
  metric LowCardinality(String),
  type LowCardinality(String),
  key Map(LowCardinality(String), String),
  value Float64,
  count UInt64,
  pipeline LowCardinality(String),
  lane LowCardinality(String),
  labels Map(LowCardinality(String), String)
) ENGINE = Kafka(msk_cluster) SETTINGS date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog';
CREATE TABLE posthog.kafka_tophog_ws (
  timestamp DateTime64(6, 'UTC'),
  metric LowCardinality(String),
  type LowCardinality(String),
  key Map(LowCardinality(String), String),
  value Float64,
  count UInt64,
  pipeline LowCardinality(String),
  lane LowCardinality(String),
  labels Map(LowCardinality(String), String)
) ENGINE = Kafka(warpstream_ingestion) SETTINGS date_time_input_format = 'best_effort', kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_tophog_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_tophog';
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
CREATE TABLE posthog.writable_app_metrics2 (
  team_id Int64,
  timestamp DateTime64(6, 'UTC'),
  app_source LowCardinality(String),
  app_source_id String,
  instance_id String,
  metric_kind LowCardinality(String),
  metric_name LowCardinality(String),
  count SimpleAggregateFunction(sum, Int64),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_app_metrics2', rand());
CREATE TABLE posthog.writable_cohort_membership (
  team_id Int64,
  cohort_id Int64,
  person_id UUID,
  status Enum8('entered'=1, 'left'=2),
  last_updated DateTime64(6) DEFAULT now64()
) ENGINE = Distributed('posthog_single_shard', 'posthog', 'cohort_membership');
CREATE TABLE posthog.writable_distinct_id_usage (
  team_id Int64,
  distinct_id String,
  minute DateTime,
  event_count UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_distinct_id_usage', sipHash64(distinct_id));
CREATE TABLE posthog.writable_flag_evaluations (
  uuid UUID,
  event LowCardinality(String),
  properties String,
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  created_at DateTime64(6, 'UTC'),
  person_id UUID,
  person_properties String DEFAULT '{}',
  person_created_at DateTime64(3),
  inserted_at DateTime64(6, 'UTC') DEFAULT timestamp,
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_flag_evaluations', sipHash64(distinct_id));
CREATE TABLE posthog.writable_heatmaps (
  session_id String,
  team_id Int64,
  distinct_id String,
  timestamp DateTime64(6, 'UTC'),
  x Int16,
  y Int16,
  scale_factor Int16,
  viewport_width Int16,
  viewport_height Int16,
  pointer_target_fixed Bool,
  current_url String,
  type LowCardinality(String),
  _timestamp DateTime,
  _offset UInt64,
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))));
CREATE TABLE posthog.writable_precalculated_events (
  team_id Int64,
  date Date,
  distinct_id String,
  person_id UUID,
  condition String,
  uuid UUID,
  source String,
  _timestamp DateTime64(6),
  _partition UInt64,
  _offset UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_precalculated_events', sipHash64(distinct_id));
CREATE TABLE posthog.writable_precalculated_person_properties (
  team_id Int64,
  distinct_id String,
  person_id UUID,
  condition String,
  matches Bool,
  source String,
  _timestamp DateTime64(6),
  _offset UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_precalculated_person_properties', sipHash64(distinct_id));
CREATE TABLE posthog.writable_tophog (
  timestamp DateTime64(6, 'UTC'),
  metric LowCardinality(String),
  type LowCardinality(String) DEFAULT 'sum',
  key Map(LowCardinality(String), String),
  value Float64,
  count UInt64 DEFAULT 0,
  pipeline LowCardinality(String),
  lane LowCardinality(String),
  labels Map(LowCardinality(String), String)
) ENGINE = Distributed('posthog', 'posthog', 'sharded_tophog', cityHash64(toString(key)));
CREATE MATERIALIZED VIEW posthog.app_metrics2_mv TO posthog.writable_app_metrics2 (team_id Int64, timestamp DateTime64(6, 'UTC'), app_source LowCardinality(String), app_source_id String, instance_id String, metric_kind String, metric_name String, count Int64, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  timestamp,
  app_source,
  app_source_id,
  instance_id,
  metric_kind,
  metric_name,
  count,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics2;
CREATE MATERIALIZED VIEW posthog.app_metrics2_ws_mv TO posthog.writable_app_metrics2 (team_id Int64, timestamp DateTime64(6, 'UTC'), app_source LowCardinality(String), app_source_id String, instance_id String, metric_kind String, metric_name String, count Int64, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  timestamp,
  app_source,
  app_source_id,
  instance_id,
  metric_kind,
  metric_name,
  count,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_app_metrics2_ws;
CREATE MATERIALIZED VIEW posthog.cohort_membership_mv TO posthog.writable_cohort_membership (team_id Int64, cohort_id Int64, person_id UUID, status String, last_updated DateTime64(6)) AS SELECT
  team_id,
  cohort_id,
  person_id,
  multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
  last_updated
FROM posthog.kafka_cohort_membership;
CREATE MATERIALIZED VIEW posthog.distinct_id_usage_mv TO posthog.writable_distinct_id_usage (team_id Int64, distinct_id String, minute DateTime('UTC'), event_count UInt8) AS SELECT team_id, distinct_id, toStartOfMinute(timestamp) AS minute, 1 AS event_count
FROM posthog.kafka_distinct_id_usage;
CREATE MATERIALIZED VIEW posthog.flag_evaluations_mv TO posthog.writable_flag_evaluations (uuid UUID, event LowCardinality(String), properties String, timestamp DateTime64(6, 'UTC'), team_id Int64, distinct_id String, created_at DateTime64(6, 'UTC'), person_id UUID, person_properties String, person_created_at DateTime64(3), inserted_at DateTime64(3), person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  uuid,
  event,
  properties,
  timestamp,
  team_id,
  distinct_id,
  created_at,
  person_id,
  if(empty(person_properties), '{}', person_properties) AS person_properties,
  person_created_at,
  now64() AS inserted_at,
  person_mode,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_flag_evaluations;
CREATE MATERIALIZED VIEW posthog.heatmaps_mv TO posthog.writable_heatmaps (session_id String, team_id Int64, distinct_id String, timestamp DateTime64(6, 'UTC'), x Int16, y Int16, scale_factor Int16, viewport_width Int16, viewport_height Int16, pointer_target_fixed Bool, current_url String, type LowCardinality(String), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  session_id,
  team_id,
  distinct_id,
  timestamp,
  x,
  y,
  scale_factor,
  viewport_width,
  viewport_height,
  pointer_target_fixed,
  current_url,
  type,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_heatmaps;
CREATE MATERIALIZED VIEW posthog.precalculated_events_mv TO posthog.writable_precalculated_events (team_id Int64, date Nullable(Date), distinct_id String, person_id UUID, condition String, uuid UUID, source String, _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64) AS SELECT
  team_id,
  ifNull(date, toDate(_timestamp)) AS date,
  distinct_id,
  person_id,
  condition,
  uuid,
  source,
  _timestamp,
  _offset,
  _partition
FROM posthog.kafka_precalculated_events;
CREATE MATERIALIZED VIEW posthog.precalculated_person_properties_mv TO posthog.writable_precalculated_person_properties (team_id Int64, distinct_id String, person_id UUID, condition String, matches Bool, source String, _timestamp Nullable(DateTime), _offset UInt64) AS SELECT
  team_id,
  distinct_id,
  person_id,
  condition,
  matches,
  source,
  _timestamp,
  _offset
FROM posthog.kafka_precalculated_person_properties;
CREATE MATERIALIZED VIEW posthog.tophog_mv TO posthog.writable_tophog (timestamp DateTime64(6, 'UTC'), metric LowCardinality(String), type LowCardinality(String), key Map(LowCardinality(String), String), value Float64, count UInt64, pipeline LowCardinality(String), lane LowCardinality(String), labels Map(LowCardinality(String), String)) AS SELECT
  timestamp,
  metric,
  type,
  key,
  value,
  count,
  pipeline,
  lane,
  labels
FROM posthog.kafka_tophog;
CREATE MATERIALIZED VIEW posthog.tophog_ws_mv TO posthog.writable_tophog (timestamp DateTime64(6, 'UTC'), metric LowCardinality(String), type LowCardinality(String), key Map(LowCardinality(String), String), value Float64, count UInt64, pipeline LowCardinality(String), lane LowCardinality(String), labels Map(LowCardinality(String), String)) AS SELECT
  timestamp,
  metric,
  type,
  key,
  value,
  count,
  pipeline,
  lane,
  labels
FROM posthog.kafka_tophog_ws;
