# LOGS prod-us overlay — env-specific / differing logs objects.
database "posthog" {
  materialized_view "kafka_logs34_avro_mv" {
    to_table = "posthog.logs34"
    query = file("sql/kafka_logs34_avro_mv.sql")
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

  materialized_view "kafka_logs_avro_billing_metrics_mv" {
    to_table = "posthog.logs_billing_metrics"
    query = file("sql/kafka_logs_avro_billing_metrics_mv.sql")
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, Float64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
}
