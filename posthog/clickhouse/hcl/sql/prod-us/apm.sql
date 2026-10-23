-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the prod-us/apm node. Apply to a fresh ClickHouse to build it.

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
  attributes Map(LowCardinality(String), String),
  retention_days Nullable(Int32),
  pattern Nullable(String),
  pattern_version Nullable(Int32)
) ENGINE = Kafka(warpstream_logs) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-logs-avro-new', kafka_num_consumers = 4, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_logs';
CREATE TABLE posthog.kafka_metrics_avro4 (
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
  series_fingerprint Nullable(Int64),
  has_labels Nullable(UInt8),
  retention_days Nullable(Int32)
) ENGINE = Kafka(warpstream_metrics) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_flush_interval_ms = 30000, kafka_format = 'Avro', kafka_group_name = 'clickhouse-metrics-avro4', kafka_max_block_size = 1000000, kafka_num_consumers = 8, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_metrics';
CREATE TABLE posthog.metrics4_input (
  uuid String,
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64,
  resource_fingerprint UInt64,
  timestamp DateTime64(6),
  observed_timestamp DateTime64(6),
  original_expiry_timestamp DateTime64(6),
  service_name LowCardinality(String),
  metric_type LowCardinality(String),
  value Float64,
  count UInt64,
  histogram_bounds Array(Float64),
  histogram_counts Array(UInt64),
  trace_id String,
  span_id String,
  trace_flags Int32,
  has_labels Bool,
  unit LowCardinality(String),
  aggregation_temporality LowCardinality(String),
  is_monotonic Bool,
  instrumentation_scope String,
  resource_attributes Map(LowCardinality(String), String),
  attributes Map(LowCardinality(String), String),
  _partition UInt32,
  _topic String,
  _offset UInt64
) ENGINE = Null();
CREATE TABLE posthog.writable_logs34 (
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
) ENGINE = Distributed('logs', 'posthog', 'logs34') SETTINGS background_insert_batch = 1;
CREATE TABLE posthog.writable_metrics4_attributes (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  service_name LowCardinality(String),
  attribute_key LowCardinality(String),
  attribute_value String,
  attribute_type LowCardinality(String),
  attribute_count SimpleAggregateFunction(sum, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'metrics4_attributes');
CREATE TABLE posthog.writable_metrics4_names (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime64(0),
  original_expiry_time_bucket DateTime64(0),
  original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6)),
  service_name LowCardinality(String),
  metric_types SimpleAggregateFunction(groupUniqArrayArray, Array(String))
) ENGINE = Distributed('logs', 'posthog', 'metrics4_names');
CREATE TABLE posthog.writable_metrics4_samples (
  team_id Int32,
  metric_name LowCardinality(String),
  time_bucket DateTime,
  series_fingerprint UInt64,
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
  timestamp_arr SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6))),
  observed_timestamp_arr SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6))),
  value_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Float64)),
  count_arr SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64)),
  histogram_counts_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64))),
  trace_id_arr SimpleAggregateFunction(groupArrayArray(10000), Array(String)),
  span_id_arr SimpleAggregateFunction(groupArrayArray(10000), Array(String)),
  trace_flags_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))
) ENGINE = Distributed('logs', 'posthog', 'metrics4_samples');
CREATE TABLE posthog.writable_metrics4_series (
  team_id Int32,
  metric_name LowCardinality(String),
  series_fingerprint UInt64,
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
  original_expiry_timestamp DateTime64(6)
) ENGINE = Distributed('logs', 'posthog', 'metrics4_series');
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
CREATE MATERIALIZED VIEW posthog.kafka_logs34_avro_mv TO posthog.writable_logs34 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), body String, severity_text String, severity_number Int32, service_name String, instrumentation_scope String, event_name String, attributes_map_str Map(String, String), resource_attributes Map(String, String), team_id Int32, original_expiry_timestamp DateTime64(6), _partition UInt64, _topic LowCardinality(String), _offset UInt64, _record_count Int64, _bytes_uncompressed Nullable(Int64), _bytes_compressed Nullable(Int64), pattern String, pattern_version UInt8) AS SELECT
  uuid,
  trace_id,
  span_id,
  trace_flags,
  timestamp,
  observed_timestamp,
  body,
  severity_text,
  severity_number,
  service_name,
  instrumentation_scope,
  event_name,
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
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) / _record_count AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) / _record_count AS _bytes_compressed,
  ifNull(pattern, '') AS pattern,
  toUInt8(ifNull(pattern_version, 0)) AS pattern_version
FROM posthog.kafka_logs_avro;
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro4_mv TO posthog.metrics4_input (uuid String, team_id Int32, metric_name String, series_fingerprint UInt64, resource_fingerprint UInt64, timestamp DateTime64(6), observed_timestamp DateTime64(6), original_expiry_timestamp DateTime64(6), service_name String, metric_type String, value Float64, count UInt64, histogram_bounds Array(Float64), histogram_counts Array(UInt64), trace_id String, span_id String, trace_flags Int32, has_labels Bool, unit String, aggregation_temporality String, is_monotonic UInt8, instrumentation_scope String, resource_attributes Map(String, String), attributes Map(String, String), _partition UInt64, _topic LowCardinality(String), _offset UInt64) AS SELECT
  uuid,
  toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
  ifNull(metric_name, '') AS metric_name,
  reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
  cityHash64(mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))) AS resource_fingerprint,
  timestamp,
  observed_timestamp,
  timestamp
  + toIntervalDay(
    assumeNotNull(
      if(
        (retention_days IS NOT NULL) AND (retention_days > 0),
        retention_days,
        toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(30))
      )
    )
  ) AS original_expiry_timestamp,
  ifNull(service_name, '') AS service_name,
  ifNull(metric_type, '') AS metric_type,
  ifNull(value, 0) AS value,
  toUInt64(ifNull(count, 1)) AS count,
  histogram_bounds,
  arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
  trace_id,
  span_id,
  ifNull(trace_flags, 0) AS trace_flags,
  toBool(ifNull(has_labels, 1)) AS has_labels,
  ifNull(unit, '') AS unit,
  ifNull(aggregation_temporality, '') AS aggregation_temporality,
  ifNull(is_monotonic, 0) AS is_monotonic,
  ifNull(instrumentation_scope, '') AS instrumentation_scope,
  if(
    toBool(ifNull(has_labels, 1)),
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)),
    CAST(map(), 'Map(String, String)')
  ) AS resource_attributes,
  if(
    toBool(ifNull(has_labels, 1)),
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)),
    CAST(map(), 'Map(String, String)')
  ) AS attributes,
  _partition,
  _topic,
  _offset
FROM posthog.kafka_metrics_avro4
WHERE kafka_metrics_avro4.series_fingerprint IS NOT NULL
SETTINGS
  min_insert_block_size_rows = 0,
  min_insert_block_size_bytes = 0;
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_attributes TO posthog.writable_metrics4_attributes (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  metric_name,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      metric_name AS metric_name,
      toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
      service_name AS service_name,
      mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
      arrayJoin(filtered_attributes) AS attribute,
      'metric' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics4_input
    WHERE has_labels
    GROUP BY
      team_id, metric_name, time_bucket, original_expiry_time_bucket, service_name, filtered_attributes
  );
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_names TO posthog.writable_metrics4_names (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6)), service_name LowCardinality(String), metric_types SimpleAggregateFunction(groupUniqArrayArray, Array(String))) AS SELECT
  team_id,
  metric_name,
  toStartOfHour(timestamp) AS time_bucket,
  toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
  maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp,
  service_name,
  groupUniqArrayArraySimpleState([toString(metric_type)]) AS metric_types
FROM posthog.metrics4_input AS input
WHERE has_labels
GROUP BY
  team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name;
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_resource_attributes TO posthog.writable_metrics4_attributes (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), service_name LowCardinality(String), attribute_key LowCardinality(String), attribute_value String, attribute_type LowCardinality(String), attribute_count SimpleAggregateFunction(sum, UInt64)) AS SELECT
  team_id,
  metric_name,
  time_bucket,
  original_expiry_time_bucket,
  service_name,
  attribute_key,
  attribute_value,
  attribute_type,
  attribute_count
FROM
  (
    SELECT
      team_id AS team_id,
      metric_name AS metric_name,
      toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
      toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
      service_name AS service_name,
      resource_attributes AS filtered_attributes,
      arrayJoin(filtered_attributes) AS attribute,
      'resource' AS attribute_type,
      attribute.1 AS attribute_key,
      attribute.2 AS attribute_value,
      sumSimpleState(1) AS attribute_count
    FROM posthog.metrics4_input
    WHERE has_labels
    GROUP BY
      team_id, metric_name, time_bucket, original_expiry_time_bucket, service_name, filtered_attributes
  );
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_samples TO posthog.writable_metrics4_samples (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime, series_fingerprint UInt64, original_expiry_date Date32, resource_fingerprint UInt64, service_name String, metric_type String, unit String, aggregation_temporality String, is_monotonic UInt8, has_labels UInt8, instrumentation_scope String, histogram_bounds Array(Float64), _topic String, timestamp_arr Array(DateTime64(6)), observed_timestamp_arr Array(DateTime64(6)), value_arr Array(Float64), count_arr Array(UInt64), histogram_counts_arr Array(Array(UInt64)), trace_id_arr Array(String), span_id_arr Array(String), trace_flags_arr Array(Int32)) AS SELECT
  team_id,
  metric_name,
  toDateTime(toStartOfHour(timestamp)) AS time_bucket,
  series_fingerprint,
  toDate32(original_expiry_timestamp) AS original_expiry_date,
  any(resource_fingerprint) AS resource_fingerprint,
  any(service_name) AS service_name,
  any(metric_type) AS metric_type,
  any(unit) AS unit,
  any(aggregation_temporality) AS aggregation_temporality,
  max(toUInt8(is_monotonic)) AS is_monotonic,
  max(toUInt8(has_labels)) AS has_labels,
  any(instrumentation_scope) AS instrumentation_scope,
  anyLast(histogram_bounds) AS histogram_bounds,
  any(_topic) AS _topic,
  groupArray(10000)(timestamp) AS timestamp_arr,
  groupArray(10000)(observed_timestamp) AS observed_timestamp_arr,
  groupArray(10000)(value) AS value_arr,
  groupArray(10000)(count) AS count_arr,
  groupArray(10000)(histogram_counts) AS histogram_counts_arr,
  groupArray(10000)(trace_id) AS trace_id_arr,
  groupArray(10000)(span_id) AS span_id_arr,
  groupArray(10000)(trace_flags) AS trace_flags_arr
FROM posthog.metrics4_input
GROUP BY
  team_id, metric_name, time_bucket, series_fingerprint, original_expiry_date;
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_series TO posthog.writable_metrics4_series (team_id Int32, metric_name LowCardinality(String), series_fingerprint UInt64, metric_type LowCardinality(String), unit LowCardinality(String), aggregation_temporality LowCardinality(String), is_monotonic Bool, service_name LowCardinality(String), instrumentation_scope String, resource_attributes Map(LowCardinality(String), String), attributes Map(LowCardinality(String), String), timestamp DateTime64(6), original_expiry_timestamp DateTime64(6)) AS SELECT
  team_id,
  metric_name,
  series_fingerprint,
  metric_type,
  unit,
  aggregation_temporality,
  is_monotonic,
  service_name,
  instrumentation_scope,
  resource_attributes,
  attributes,
  timestamp,
  original_expiry_timestamp
FROM posthog.metrics4_input
WHERE has_labels;
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
