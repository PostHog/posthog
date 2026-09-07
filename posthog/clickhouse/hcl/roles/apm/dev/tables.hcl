# The APM ingest chain, as dev runs it on its ingestion-apm nodes: the Kafka
# consumers for logs, traces and metrics, their views, and the writable proxies
# they feed. The prod envs still run this chain on their logs nodes, so an object
# the logs role already declares is restated here rather than declared twice. dev
# also tunes its consumers smaller than prod does.
database "posthog" {
  table "kafka_logs_avro" {
    override = true
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "String"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "retention_days" {
      type = "Nullable(Int32)"
    }
    column "pattern" {
      type = "Nullable(String)"
    }
    column "pattern_version" {
      type = "Nullable(Int32)"
    }
    engine "kafka" {
      collection           = "warpstream_logs"
      topic_list           = "clickhouse_logs"
      group_name           = "clickhouse-logs-avro-new"
      format               = "Avro"
      num_consumers        = 4
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 1000
      flush_interval_ms    = 10000
      thread_per_consumer  = true
    }
  }

  table "kafka_metrics_avro" {
    override = true
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Nullable(Int32)"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "Nullable(String)"
    }
    column "metric_name" {
      type = "Nullable(String)"
    }
    column "metric_type" {
      type = "Nullable(String)"
    }
    column "value" {
      type = "Nullable(Float64)"
    }
    column "count" {
      type = "Nullable(Int64)"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(Int64)"
    }
    column "unit" {
      type = "Nullable(String)"
    }
    column "aggregation_temporality" {
      type = "Nullable(String)"
    }
    column "is_monotonic" {
      type = "Nullable(UInt8)"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "instrumentation_scope" {
      type = "Nullable(String)"
    }
    column "attributes" {
      type = "Map(String, String)"
    }
    column "series_fingerprint" {
      type = "Nullable(Int64)"
    }
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro-new"
      format               = "Avro"
      num_consumers        = 4
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 1000
      flush_interval_ms    = 10000
      thread_per_consumer  = true
    }
  }

  table "kafka_trace_spans_avro" {
    override = true
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "String"
    }
    column "kind" {
      type = "Int32"
    }
    column "flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "dropped_attributes_count" {
      type = "Int32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "dropped_events_count" {
      type = "Int32"
    }
    column "links" {
      type = "Array(String)"
    }
    column "dropped_links_count" {
      type = "Int32"
    }
    column "status_code" {
      type = "Int32"
    }
    engine "kafka" {
      collection           = "warpstream_traces"
      topic_list           = "clickhouse_traces"
      group_name           = "clickhouse-traces-avro"
      format               = "Avro"
      num_consumers        = 4
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 1000
      flush_interval_ms    = 10000
      thread_per_consumer  = true
    }
  }

  table "writable_logs34" {
    override = true
    settings = {
      background_insert_batch = "1"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "level" {
      type  = "String"
      alias = "severity_text"
    }
    column "mat_body_ipv4_matches" {
      type  = "Array(String)"
      alias = "extractAll(body, '(\\\\d\\\\.((25[0-5]|(2[0-4]|1(0, 1)[0-9])(0, 1)[0-9])\\\\.)(2, 2)([0-9]))')"
    }
    column "time_minute" {
      type  = "DateTime"
      alias = "toStartOfMinute(timestamp)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_bytes_uncompressed" {
      type = "UInt64"
    }
    column "_bytes_compressed" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "UInt64"
    }
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }

  table "writable_metric_samples1" {
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "timestamp" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    column "value" {
      type  = "Float64"
      codec = "Gorilla(8)"
    }
    column "count" {
      type    = "UInt64"
      default = "1"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metric_samples1"
    }
  }

  table "writable_metric_series1" {
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "DoubleDelta"
    }
    column "metric_type" {
      type = "LowCardinality(String)"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "aggregation_temporality" {
      type = "LowCardinality(String)"
    }
    column "is_monotonic" {
      type    = "Bool"
      default = "false"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "last_seen" {
      type  = "DateTime64(6)"
      codec = "DoubleDelta"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metric_series1"
    }
  }

  table "writable_metrics1" {
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfDay(timestamp)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "metric_type" {
      type = "LowCardinality(String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type    = "UInt64"
      default = "1"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "aggregation_temporality" {
      type = "LowCardinality(String)"
    }
    column "is_monotonic" {
      type    = "Bool"
      default = "false"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes_map_float" {
      type = "Map(LowCardinality(String), Float64)"
    }
    column "time_minute" {
      type  = "DateTime"
      alias = "toStartOfMinute(timestamp)"
    }
    column "attributes" {
      type  = "Map(String, String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics1"
    }
  }

  table "writable_metrics_kafka_metrics" {
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime64(9))"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics_kafka_metrics"
    }
  }

  table "writable_trace_spans" {
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfInterval(timestamp, toIntervalHour(4))"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "is_root_span" {
      type         = "Bool"
      materialized = "replaceAll(trimRight(parent_span_id, '='), 'A', '') = ''"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "LowCardinality(String)"
    }
    column "kind" {
      type = "Int8"
    }
    column "flags" {
      type = "UInt32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "created_at" {
      type         = "DateTime64(6)"
      materialized = "now()"
    }
    column "duration_nano" {
      type         = "UInt64"
      materialized = "toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000"
    }
    column "status_code" {
      type = "Int16"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type  = "Map(LowCardinality(String), String)"
      alias = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)"
    }
    column "attributes_map_float" {
      type         = "Map(LowCardinality(String), Float64)"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))"
    }
    column "attributes_map_datetime" {
      type         = "Map(LowCardinality(String), DateTime64(6))"
      materialized = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "links" {
      type = "Array(String)"
    }
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_bytes_uncompressed" {
      type = "UInt64"
    }
    column "_bytes_compressed" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "trace_spans"
    }
  }

  materialized_view "kafka_logs34_avro_mv" {
    override = true
    to_table = "posthog.writable_logs34"
    query    = <<SQL
SELECT
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
FROM posthog.kafka_logs_avro
SQL

    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "body" {
      type = "String"
    }
    column "severity_text" {
      type = "String"
    }
    column "severity_number" {
      type = "Int32"
    }
    column "service_name" {
      type = "String"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "event_name" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(String, String)"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_timestamp" {
      type = "Nullable(DateTime64(6))"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "_topic" {
      type = "LowCardinality(String)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "Int64"
    }
    column "_bytes_uncompressed" {
      type = "Nullable(Float64)"
    }
    column "_bytes_compressed" {
      type = "Nullable(Float64)"
    }
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
    }
  }

  materialized_view "kafka_metrics_avro_kafka_metrics_mv" {
    override = true
    to_table = "posthog.writable_metrics_kafka_metrics"
    query    = <<SQL
SELECT
  _partition,
  _topic,
  maxSimpleState(_offset) AS max_offset,
  maxSimpleState(observed_timestamp) AS max_observed_timestamp,
  maxSimpleState(timestamp) AS max_timestamp,
  maxSimpleState(now()) AS max_created_at,
  maxSimpleState(now() - observed_timestamp) AS max_lag
FROM posthog.kafka_metrics_avro
GROUP BY
  _partition, _topic
SQL

    column "_partition" {
      type = "UInt64"
    }
    column "_topic" {
      type = "LowCardinality(String)"
    }
    column "max_offset" {
      type = "SimpleAggregateFunction(max, UInt64)"
    }
    column "max_observed_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
    column "max_created_at" {
      type = "SimpleAggregateFunction(max, DateTime)"
    }
    column "max_lag" {
      type = "SimpleAggregateFunction(max, Decimal(18, 6))"
    }
  }

  materialized_view "kafka_metrics_avro_mv" {
    override = true
    to_table = "posthog.writable_metrics1"
    query    = <<SQL
SELECT
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
  min_insert_block_size_bytes = 0
SQL

    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "metric_name" {
      type = "String"
    }
    column "metric_type" {
      type = "String"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
    }
    column "unit" {
      type = "String"
    }
    column "aggregation_temporality" {
      type = "String"
    }
    column "is_monotonic" {
      type = "UInt8"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(String, String)"
    }
    column "attributes_map_float" {
      type = "Map(String, Nullable(Float64))"
    }
    column "team_id" {
      type = "Int32"
    }
  }

  materialized_view "kafka_metrics_avro_to_metric_samples" {
    override = true
    to_table = "posthog.writable_metric_samples1"
    query    = <<SQL
SELECT
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
  min_insert_block_size_bytes = 0
SQL

    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "String"
    }
    column "series_fingerprint" {
      type = "UInt64"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "histogram_bounds" {
      type = "Array(Float64)"
    }
    column "histogram_counts" {
      type = "Array(UInt64)"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "trace_flags" {
      type = "Int32"
    }
  }

  materialized_view "kafka_metrics_avro_to_metric_series" {
    override = true
    to_table = "posthog.writable_metric_series1"
    query    = <<SQL
SELECT
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
  min_insert_block_size_bytes = 0
SQL

    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "String"
    }
    column "series_fingerprint" {
      type = "UInt64"
    }
    column "metric_type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "aggregation_temporality" {
      type = "String"
    }
    column "is_monotonic" {
      type = "UInt8"
    }
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "attributes" {
      type = "Map(String, String)"
    }
    column "last_seen" {
      type = "DateTime64(6)"
    }
  }

  materialized_view "kafka_trace_spans_avro_mv" {
    override = true
    to_table = "posthog.writable_trace_spans"
    query    = <<SQL
SELECT
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
FROM posthog.kafka_trace_spans_avro
SQL

    column "uuid" {
      type = "String"
    }
    column "trace_id" {
      type = "String"
    }
    column "span_id" {
      type = "String"
    }
    column "parent_span_id" {
      type = "String"
    }
    column "trace_state" {
      type = "String"
    }
    column "name" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "end_time" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "String"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "events" {
      type = "Array(String)"
    }
    column "links" {
      type = "Array(String)"
    }
    column "kind" {
      type = "Int8"
    }
    column "flags" {
      type = "UInt32"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "status_code" {
      type = "Int16"
    }
    column "attributes_map_str" {
      type = "Map(String, String)"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "_partition" {
      type = "UInt64"
    }
    column "_topic" {
      type = "LowCardinality(String)"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_record_count" {
      type = "Int64"
    }
    column "_bytes_uncompressed" {
      type = "Nullable(Int64)"
    }
    column "_bytes_compressed" {
      type = "Nullable(Int64)"
    }
  }
}
