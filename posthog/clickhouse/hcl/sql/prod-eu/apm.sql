-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the prod-eu/apm node. Apply to a fresh ClickHouse to build it.

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
  original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6))
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
CREATE MATERIALIZED VIEW posthog.metrics4_input_to_metrics4_names TO posthog.writable_metrics4_names (team_id Int32, metric_name LowCardinality(String), time_bucket DateTime64(0), original_expiry_time_bucket DateTime64(0), original_expiry_timestamp SimpleAggregateFunction(max, DateTime64(6))) AS SELECT
  team_id,
  metric_name,
  toStartOfHour(timestamp) AS time_bucket,
  toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
  maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
FROM posthog.metrics4_input AS input
WHERE has_labels
GROUP BY
  team_id, time_bucket, metric_name, original_expiry_time_bucket;
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
