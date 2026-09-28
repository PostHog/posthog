-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit.
-- Full CREATE schema for the local-multi/events node. Apply to a fresh ClickHouse to build it.

CREATE TABLE posthog.kafka_events_json_native_json (
  uuid UUID,
  event String,
  properties String CODEC(ZSTD(3)),
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  elements_chain String,
  created_at DateTime64(6, 'UTC'),
  person_id UUID,
  person_created_at DateTime64(3),
  person_properties String CODEC(ZSTD(3)),
  group0_properties String CODEC(ZSTD(3)),
  group1_properties String CODEC(ZSTD(3)),
  group2_properties String CODEC(ZSTD(3)),
  group3_properties String CODEC(ZSTD(3)),
  group4_properties String CODEC(ZSTD(3)),
  group0_created_at DateTime64(3),
  group1_created_at DateTime64(3),
  group2_created_at DateTime64(3),
  group3_created_at DateTime64(3),
  group4_created_at DateTime64(3),
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2),
  historical_migration Bool,
  dmat_string_0 Nullable(String),
  dmat_string_1 Nullable(String),
  dmat_string_2 Nullable(String),
  dmat_string_3 Nullable(String),
  dmat_string_4 Nullable(String),
  dmat_string_5 Nullable(String),
  dmat_string_6 Nullable(String),
  dmat_string_7 Nullable(String),
  dmat_string_8 Nullable(String),
  dmat_string_9 Nullable(String),
  captured_at Nullable(DateTime64(6, 'UTC'))
) ENGINE = Kafka(msk_cluster) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_events_json_native_json', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_events_json';
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
) ENGINE = Kafka(warpstream_logs) SETTINGS input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-logs-avro-new', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_logs';
CREATE TABLE posthog.kafka_person_property_mutation_log (
  team_id Int64,
  uuid UUID,
  properties String
) ENGINE = Kafka(warpstream_ingestion) SETTINGS kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_person_property_mutation_log', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_events_json';
CREATE TABLE posthog.person_property_mutation_log (
  team_id Int64,
  event_uuid UUID,
  properties String,
  ingested_at DateTime('UTC')
) ENGINE = Distributed('aux', 'posthog', 'person_property_mutation_log_data');
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
CREATE TABLE posthog.writable_events_json (
  uuid UUID,
  event String,
  properties JSON(`$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String),
  temporary_properties JSON(max_dynamic_paths=32),
  timestamp DateTime64(6, 'UTC'),
  team_id Int64,
  distinct_id String,
  created_at DateTime64(6, 'UTC') DEFAULT now(),
  _timestamp DateTime,
  _offset UInt64,
  elements_chain String,
  person_id UUID,
  person_properties JSON(max_dynamic_paths=256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String)),
  group0_properties String,
  group1_properties String,
  group2_properties String,
  group3_properties String,
  group4_properties String,
  person_created_at DateTime64(3),
  group0_created_at DateTime64(3),
  group1_created_at DateTime64(3),
  group2_created_at DateTime64(3),
  group3_created_at DateTime64(3),
  group4_created_at DateTime64(3),
  inserted_at DateTime64(6, 'UTC') DEFAULT now64(),
  person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2),
  consumer_breadcrumbs Array(String),
  historical_migration Bool,
  total_event_size UInt32,
  captured_at DateTime64(6, 'UTC') DEFAULT now(),
  _partition UInt64
) ENGINE = Distributed('posthog', 'posthog', 'sharded_events_json', sipHash64(distinct_id));
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
CREATE MATERIALIZED VIEW posthog.events_json_table_mv TO posthog.writable_events_json (uuid UUID, event String, properties String, temporary_properties String, inserted_at DateTime64(3), timestamp DateTime64(6, 'UTC'), team_id Int64, distinct_id String, elements_chain String, created_at DateTime64(6, 'UTC'), person_id UUID, person_properties String, person_created_at DateTime64(3), group0_properties String, group1_properties String, group2_properties String, group3_properties String, group4_properties String, group0_created_at DateTime64(3), group1_created_at DateTime64(3), group2_created_at DateTime64(3), group3_created_at DateTime64(3), group4_created_at DateTime64(3), person_mode Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2), historical_migration Bool, captured_at DateTime64(6, 'UTC'), _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64, consumer_breadcrumbs Array(String), total_event_size UInt32) AS SELECT
  *,
  accurateCast(byteSize(*) + byteSize(toUInt32(0)), 'UInt32') AS total_event_size
FROM
  (
    SELECT
      uuid,
      event,
      if(
        isValidJSON(source.properties) AND startsWith(trimLeft(source.properties), '{'),
        JSONCleanPostHogEventProperties(source.properties),
        concat('{"$unparseable_properties":', toJSONString(source.properties), '}')
      ) AS properties,
      JSONCleanPostHogTemporaryProperties(
        if(
          isValidJSON(source.properties) AND startsWith(trimLeft(source.properties), '{'),
          source.properties,
          '{}'
        )
      ) AS temporary_properties,
      now64() AS inserted_at,
      timestamp,
      team_id,
      distinct_id,
      elements_chain,
      created_at,
      person_id,
      if(
        isValidJSON(source.person_properties)
        AND startsWith(trimLeft(source.person_properties), '{'),
        JSONCleanPostHogPersonProperties(source.person_properties),
        concat('{"$unparseable_properties":', toJSONString(source.person_properties), '}')
      ) AS person_properties,
      person_created_at,
      group0_properties,
      group1_properties,
      group2_properties,
      group3_properties,
      group4_properties,
      group0_created_at,
      group1_created_at,
      group2_created_at,
      group3_created_at,
      group4_created_at,
      person_mode,
      historical_migration,
      coalesce(captured_at, created_at) AS captured_at,
      _timestamp,
      _offset,
      _partition,
      arrayMap(
        i -> (_headers.value[i]),
        arrayFilter(
          i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'),
          arrayEnumerate(_headers.name)
        )
      ) AS consumer_breadcrumbs
    FROM posthog.kafka_events_json_native_json AS source
  )
SETTINGS
  input_format_try_infer_dates = 0,
  input_format_try_infer_datetimes = 0;
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
CREATE MATERIALIZED VIEW posthog.person_property_mutation_log_mv TO posthog.person_property_mutation_log (team_id Int64, event_uuid UUID, properties String, ingested_at DateTime('UTC')) AS SELECT
  team_id,
  uuid AS event_uuid,
  concat(
    '{',
    arrayStringConcat(
      arrayMap(
        property -> concat(toJSONString(property.1), ':', property.2),
        arrayFilter(
          property -> property.1 IN ('$set', '$set_once', '$unset'),
          JSONExtractKeysAndValuesRaw(source.properties)
        )
      ),
      ','
    ),
    '}'
  ) AS properties,
  toDateTime(_timestamp, 'UTC') AS ingested_at
FROM kafka_person_property_mutation_log AS source
WHERE
  JSONHas(source.properties, '$set')
OR
  JSONHas(source.properties, '$set_once')
OR
  JSONHas(source.properties, '$unset');
