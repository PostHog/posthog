database "posthog" {
  table "kafka_metrics_avro2" {
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
    column "has_labels" {
      type = "Nullable(UInt8)"
    }
    column "retention_days" {
      type = "Nullable(Int32)"
    }
    engine "kafka" {
      collection           = "warpstream_metrics"
      topic_list           = "clickhouse_metrics"
      group_name           = "clickhouse-metrics-avro2"
      format               = "Avro"
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
    settings = {
      input_format_avro_allow_missing_fields = "1"
    }
  }
  table "metrics2_input" {
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type = "UInt64"
    }
    column "resource_fingerprint" {
      type = "UInt64"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "observed_timestamp" {
      type = "DateTime64(6)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "metric_type" {
      type = "LowCardinality(String)"
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
    column "has_labels" {
      type = "Bool"
    }
    column "unit" {
      type = "LowCardinality(String)"
    }
    column "aggregation_temporality" {
      type = "LowCardinality(String)"
    }
    column "is_monotonic" {
      type = "Bool"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
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
    engine "null" {}
  }
}
