# The metrics4 ingest chain runs on the APM ingestion nodes.
# Its Distributed tables write to the metrics4 data tables on the logs cluster.
database "posthog" {
  table "kafka_metrics_avro4" {
    column "uuid" { type = "String" }
    column "trace_id" { type = "String" }
    column "span_id" { type = "String" }
    column "trace_flags" { type = "Nullable(Int32)" }
    column "timestamp" { type = "DateTime64(6)" }
    column "observed_timestamp" { type = "DateTime64(6)" }
    column "service_name" { type = "Nullable(String)" }
    column "metric_name" { type = "Nullable(String)" }
    column "metric_type" { type = "Nullable(String)" }
    column "value" { type = "Nullable(Float64)" }
    column "count" { type = "Nullable(Int64)" }
    column "histogram_bounds" { type = "Array(Float64)" }
    column "histogram_counts" { type = "Array(Int64)" }
    column "unit" { type = "Nullable(String)" }
    column "aggregation_temporality" { type = "Nullable(String)" }
    column "is_monotonic" { type = "Nullable(UInt8)" }
    column "resource_attributes" { type = "Map(String, String)" }
    column "instrumentation_scope" { type = "Nullable(String)" }
    column "attributes" { type = "Map(String, String)" }
    column "series_fingerprint" { type = "Nullable(Int64)" }
    column "has_labels" { type = "Nullable(UInt8)" }
    column "retention_days" { type = "Nullable(Int32)" }
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro4"
      format               = "Avro"
      num_consumers        = 8
      max_block_size       = 1000000
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      flush_interval_ms    = 30000
      thread_per_consumer  = true
    }
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }

  table "metrics4_input" {
    column "uuid" { type = "String" }
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "series_fingerprint" { type = "UInt64" }
    column "resource_fingerprint" { type = "UInt64" }
    column "timestamp" { type = "DateTime64(6)" }
    column "observed_timestamp" { type = "DateTime64(6)" }
    column "original_expiry_timestamp" { type = "DateTime64(6)" }
    column "service_name" { type = "LowCardinality(String)" }
    column "metric_type" { type = "LowCardinality(String)" }
    column "value" { type = "Float64" }
    column "count" { type = "UInt64" }
    column "histogram_bounds" { type = "Array(Float64)" }
    column "histogram_counts" { type = "Array(UInt64)" }
    column "trace_id" { type = "String" }
    column "span_id" { type = "String" }
    column "trace_flags" { type = "Int32" }
    column "has_labels" { type = "Bool" }
    column "unit" { type = "LowCardinality(String)" }
    column "aggregation_temporality" { type = "LowCardinality(String)" }
    column "is_monotonic" { type = "Bool" }
    column "instrumentation_scope" { type = "String" }
    column "resource_attributes" { type = "Map(LowCardinality(String), String)" }
    column "attributes" { type = "Map(LowCardinality(String), String)" }
    column "_partition" { type = "UInt32" }
    column "_topic" { type = "String" }
    column "_offset" { type = "UInt64" }
    engine "null" {}
  }

  table "writable_metrics4_samples" {
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime" }
    column "series_fingerprint" { type = "UInt64" }
    column "original_expiry_date" { type = "Date32" }
    column "resource_fingerprint" { type = "SimpleAggregateFunction(any, UInt64)" }
    column "service_name" { type = "SimpleAggregateFunction(any, LowCardinality(String))" }
    column "metric_type" { type = "SimpleAggregateFunction(any, LowCardinality(String))" }
    column "unit" { type = "SimpleAggregateFunction(any, LowCardinality(String))" }
    column "aggregation_temporality" { type = "SimpleAggregateFunction(any, LowCardinality(String))" }
    column "is_monotonic" { type = "SimpleAggregateFunction(max, UInt8)" }
    column "has_labels" { type = "SimpleAggregateFunction(max, UInt8)" }
    column "instrumentation_scope" { type = "SimpleAggregateFunction(any, String)" }
    column "histogram_bounds" { type = "SimpleAggregateFunction(anyLast, Array(Float64))" }
    column "_topic" { type = "SimpleAggregateFunction(any, LowCardinality(String))" }
    column "timestamp_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))" }
    column "observed_timestamp_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))" }
    column "value_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Float64))" }
    column "count_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64))" }
    column "histogram_counts_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64)))" }
    column "trace_id_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" }
    column "span_id_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" }
    column "trace_flags_arr" { type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))" }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics4_samples"
    }
  }

  table "writable_metrics4_series" {
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "series_fingerprint" { type = "UInt64" }
    column "metric_type" { type = "LowCardinality(String)" }
    column "unit" { type = "LowCardinality(String)" }
    column "aggregation_temporality" { type = "LowCardinality(String)" }
    column "is_monotonic" {
      type    = "Bool"
      default = "false"
    }
    column "service_name" { type = "LowCardinality(String)" }
    column "instrumentation_scope" { type = "String" }
    column "resource_attributes" { type = "Map(LowCardinality(String), String)" }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "attributes" { type = "Map(LowCardinality(String), String)" }
    column "timestamp" { type = "DateTime64(6)" }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfHour(timestamp)"
    }
    column "original_expiry_timestamp" { type = "DateTime64(6)" }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics4_series"
    }
  }

  table "writable_metrics4_names" {
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_timestamp" { type = "SimpleAggregateFunction(max, DateTime64(6))" }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics4_names"
    }
  }

  table "writable_metrics4_attributes" {
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_time_bucket" { type = "DateTime64(0)" }
    column "service_name" { type = "LowCardinality(String)" }
    column "attribute_key" { type = "LowCardinality(String)" }
    column "attribute_value" { type = "String" }
    column "attribute_type" { type = "LowCardinality(String)" }
    column "attribute_count" { type = "SimpleAggregateFunction(sum, UInt64)" }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "metrics4_attributes"
    }
  }

  materialized_view "kafka_metrics_avro4_mv" {
    to_table = "posthog.metrics4_input"
    query    = file("sql/kafka_metrics_avro4_mv.sql")
    column "uuid" { type = "String" }
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "String" }
    column "series_fingerprint" { type = "UInt64" }
    column "resource_fingerprint" { type = "UInt64" }
    column "timestamp" { type = "DateTime64(6)" }
    column "observed_timestamp" { type = "DateTime64(6)" }
    column "original_expiry_timestamp" { type = "DateTime64(6)" }
    column "service_name" { type = "String" }
    column "metric_type" { type = "String" }
    column "value" { type = "Float64" }
    column "count" { type = "UInt64" }
    column "histogram_bounds" { type = "Array(Float64)" }
    column "histogram_counts" { type = "Array(UInt64)" }
    column "trace_id" { type = "String" }
    column "span_id" { type = "String" }
    column "trace_flags" { type = "Int32" }
    column "has_labels" { type = "Bool" }
    column "unit" { type = "String" }
    column "aggregation_temporality" { type = "String" }
    column "is_monotonic" { type = "UInt8" }
    column "instrumentation_scope" { type = "String" }
    column "resource_attributes" { type = "Map(String, String)" }
    column "attributes" { type = "Map(String, String)" }
    column "_partition" { type = "UInt64" }
    column "_topic" { type = "LowCardinality(String)" }
    column "_offset" { type = "UInt64" }
  }

  materialized_view "metrics4_input_to_metrics4_samples" {
    to_table = "posthog.writable_metrics4_samples"
    query    = file("sql/metrics4_input_to_metrics4_samples.sql")
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime" }
    column "series_fingerprint" { type = "UInt64" }
    column "original_expiry_date" { type = "Date32" }
    column "resource_fingerprint" { type = "UInt64" }
    column "service_name" { type = "String" }
    column "metric_type" { type = "String" }
    column "unit" { type = "String" }
    column "aggregation_temporality" { type = "String" }
    column "is_monotonic" { type = "UInt8" }
    column "has_labels" { type = "UInt8" }
    column "instrumentation_scope" { type = "String" }
    column "histogram_bounds" { type = "Array(Float64)" }
    column "_topic" { type = "String" }
    column "timestamp_arr" { type = "Array(DateTime64(6))" }
    column "observed_timestamp_arr" { type = "Array(DateTime64(6))" }
    column "value_arr" { type = "Array(Float64)" }
    column "count_arr" { type = "Array(UInt64)" }
    column "histogram_counts_arr" { type = "Array(Array(UInt64))" }
    column "trace_id_arr" { type = "Array(String)" }
    column "span_id_arr" { type = "Array(String)" }
    column "trace_flags_arr" { type = "Array(Int32)" }
  }

  materialized_view "metrics4_input_to_metrics4_series" {
    to_table = "posthog.writable_metrics4_series"
    query    = file("sql/metrics4_input_to_metrics4_series.sql")
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "series_fingerprint" { type = "UInt64" }
    column "metric_type" { type = "LowCardinality(String)" }
    column "unit" { type = "LowCardinality(String)" }
    column "aggregation_temporality" { type = "LowCardinality(String)" }
    column "is_monotonic" { type = "Bool" }
    column "service_name" { type = "LowCardinality(String)" }
    column "instrumentation_scope" { type = "String" }
    column "resource_attributes" { type = "Map(LowCardinality(String), String)" }
    column "attributes" { type = "Map(LowCardinality(String), String)" }
    column "timestamp" { type = "DateTime64(6)" }
    column "original_expiry_timestamp" { type = "DateTime64(6)" }
  }

  materialized_view "metrics4_input_to_metrics4_names" {
    to_table = "posthog.writable_metrics4_names"
    query    = file("sql/metrics4_input_to_metrics4_names.sql")
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_timestamp" { type = "SimpleAggregateFunction(max, DateTime64(6))" }
  }

  materialized_view "metrics4_input_to_metrics4_attributes" {
    to_table = "posthog.writable_metrics4_attributes"
    query    = file("sql/metrics4_input_to_metrics4_attributes.sql")
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_time_bucket" { type = "DateTime64(0)" }
    column "service_name" { type = "LowCardinality(String)" }
    column "attribute_key" { type = "LowCardinality(String)" }
    column "attribute_value" { type = "String" }
    column "attribute_type" { type = "LowCardinality(String)" }
    column "attribute_count" { type = "SimpleAggregateFunction(sum, UInt64)" }
  }

  materialized_view "metrics4_input_to_metrics4_resource_attributes" {
    to_table = "posthog.writable_metrics4_attributes"
    query    = file("sql/metrics4_input_to_metrics4_resource_attributes.sql")
    column "team_id" { type = "Int32" }
    column "metric_name" { type = "LowCardinality(String)" }
    column "time_bucket" { type = "DateTime64(0)" }
    column "original_expiry_time_bucket" { type = "DateTime64(0)" }
    column "service_name" { type = "LowCardinality(String)" }
    column "attribute_key" { type = "LowCardinality(String)" }
    column "attribute_value" { type = "String" }
    column "attribute_type" { type = "LowCardinality(String)" }
    column "attribute_count" { type = "SimpleAggregateFunction(sum, UInt64)" }
  }
}
