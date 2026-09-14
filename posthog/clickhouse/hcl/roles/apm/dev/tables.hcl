# What only dev's ingestion-apm nodes run: the writable proxies the ingest chain
# feeds, and dev's own consumer tuning on top of the shared ingest layers. dev
# runs its consumers smaller than the prod clusters do.
database "posthog" {

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

  patch_table "kafka_logs_avro" {
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

  patch_table "kafka_metrics_avro" {
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
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }

  patch_table "kafka_trace_spans_avro" {
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
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }

  # Same views the logs role runs, pointed at a different destination: the storage
  # tables live on the logs nodes, so these write through the writable proxies above
  # rather than straight into local tables.
  #
  # One is restated in full: its column set matches but the order does not, and no
  # patch can reorder inherited columns. See PostHog/chschema#240.
  patch_materialized_view "kafka_logs34_avro_mv" {
    to_table = "posthog.writable_logs34"
    modify_column "original_expiry_timestamp" {
      type = "Nullable(DateTime64(6))"
    }
    modify_column "_bytes_uncompressed" {
      type = "Nullable(Float64)"
    }
    modify_column "_bytes_compressed" {
      type = "Nullable(Float64)"
    }
  }

  patch_materialized_view "kafka_metrics_avro_mv" {
    to_table = "posthog.writable_metrics1"
  }

  patch_materialized_view "kafka_metrics_avro_kafka_metrics_mv" {
    to_table = "posthog.writable_metrics_kafka_metrics"
  }

  patch_materialized_view "kafka_metrics_avro_to_metric_samples" {
    to_table = "posthog.writable_metric_samples1"
  }

  patch_materialized_view "kafka_metrics_avro_to_metric_series" {
    to_table = "posthog.writable_metric_series1"
  }

  patch_materialized_view "kafka_trace_spans_avro_mv" {
    to_table = "posthog.writable_trace_spans"

    modify_column "attributes_map_str" {
      type = "Map(String, String)"
    }
    modify_column "resource_attributes" {
      type = "Map(String, String)"
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
