-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the dev/apm node. Apply to a fresh ClickHouse to build it.

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
) ENGINE = Kafka(warpstream_logs) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_flush_interval_ms = 10000, kafka_format = 'Avro', kafka_group_name = 'clickhouse-logs-avro-new', kafka_num_consumers = 4, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_logs';
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
) ENGINE = Kafka(warpstream_metrics) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_flush_interval_ms = 10000, kafka_format = 'Avro', kafka_group_name = 'clickhouse-metrics-avro-new', kafka_num_consumers = 4, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_metrics';
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
) ENGINE = Kafka(warpstream_traces) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_flush_interval_ms = 10000, kafka_format = 'Avro', kafka_group_name = 'clickhouse-traces-avro', kafka_num_consumers = 4, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_traces';
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
CREATE TABLE posthog.writable_metric_samples1 (
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
CREATE TABLE posthog.writable_metric_series1 (
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
CREATE TABLE posthog.writable_metrics1 (
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
  value Float64,
  count UInt64 DEFAULT 1,
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
CREATE TABLE posthog.writable_metrics_kafka_metrics (
  _partition UInt32,
  _topic String,
  max_offset SimpleAggregateFunction(max, UInt64),
  max_observed_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_timestamp SimpleAggregateFunction(max, DateTime64(9)),
  max_created_at SimpleAggregateFunction(max, DateTime64(9)),
  max_lag SimpleAggregateFunction(max, UInt64)
) ENGINE = Distributed('logs', 'posthog', 'metrics_kafka_metrics');
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
CREATE TABLE posthog.writable_trace_spans (
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
CREATE MATERIALIZED VIEW posthog.kafka_logs34_avro_mv TO posthog.writable_logs34 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), body String, severity_text String, severity_number Int32, service_name String, instrumentation_scope String, event_name String, attributes_map_str Map(String, String), resource_attributes Map(String, String), team_id Int32, original_expiry_timestamp Nullable(DateTime64(6)), _partition UInt64, _topic LowCardinality(String), _offset UInt64, _record_count Int64, _bytes_uncompressed Nullable(Float64), _bytes_compressed Nullable(Float64), pattern String, pattern_version UInt8) AS SELECT
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
  observed_timestamp
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
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_kafka_metrics_mv TO posthog.writable_metrics_kafka_metrics (_partition UInt64, _topic LowCardinality(String), max_offset SimpleAggregateFunction(max, UInt64), max_observed_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_timestamp SimpleAggregateFunction(max, DateTime64(6)), max_created_at SimpleAggregateFunction(max, DateTime), max_lag SimpleAggregateFunction(max, Decimal(18, 6))) AS SELECT
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
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_mv TO posthog.writable_metrics1 (uuid String, trace_id String, span_id String, trace_flags Int32, timestamp DateTime64(6), observed_timestamp DateTime64(6), service_name String, metric_name String, metric_type String, value Float64, count UInt64, histogram_bounds Array(Float64), histogram_counts Array(UInt64), unit String, aggregation_temporality String, is_monotonic UInt8, resource_attributes Map(String, String), instrumentation_scope String, attributes_map_str Map(String, String), attributes_map_float Map(String, Nullable(Float64)), team_id Int32) AS SELECT
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
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_to_metric_samples TO posthog.writable_metric_samples1 (team_id Int32, metric_name String, series_fingerprint UInt64, timestamp DateTime64(6), value Float64, count UInt64, histogram_bounds Array(Float64), histogram_counts Array(UInt64), trace_id String, span_id String, trace_flags Int32) AS SELECT
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
CREATE MATERIALIZED VIEW posthog.kafka_metrics_avro_to_metric_series TO posthog.writable_metric_series1 (team_id Int32, metric_name String, series_fingerprint UInt64, metric_type String, unit String, aggregation_temporality String, is_monotonic UInt8, service_name String, resource_attributes Map(String, String), attributes Map(String, String), last_seen DateTime64(6)) AS SELECT
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
CREATE MATERIALIZED VIEW posthog.kafka_trace_spans_avro_mv TO posthog.writable_trace_spans (uuid String, trace_id String, span_id String, parent_span_id String, trace_state String, name String, kind Int8, flags UInt32, timestamp DateTime64(6), end_time DateTime64(6), observed_timestamp DateTime64(6), service_name String, resource_attributes Map(String, String), instrumentation_scope String, attributes_map_str Map(String, String), dropped_attributes_count UInt32, events Array(String), dropped_events_count UInt32, links Array(String), dropped_links_count UInt32, status_code Int16, team_id Int32, original_expiry_timestamp DateTime64(6), _partition UInt64, _topic LowCardinality(String), _offset UInt64, _record_count Int64, _bytes_uncompressed Nullable(Int64), _bytes_compressed Nullable(Int64)) AS SELECT
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
  observed_timestamp
  + toIntervalDay(
    toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15))
  ) AS original_expiry_timestamp,
  _partition,
  _topic,
  _offset,
  toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')]) AS _bytes_uncompressed,
  toInt64OrNull(_headers.value[indexOf(_headers.name, 'bytes_compressed')]) AS _bytes_compressed
FROM posthog.kafka_trace_spans_avro;
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
