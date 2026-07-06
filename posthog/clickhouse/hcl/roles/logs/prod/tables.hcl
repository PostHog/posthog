# LOGS role, prod only — the Kafka metrics ingest MVs. Env-identical across
# prod-us / prod-eu (both read the WarpStream metrics_avro topic straight into the
# metric_samples1 / metric_series1 tables). Not present in dev/local, which have no
# metrics ingest path.

database "posthog" {
  materialized_view "kafka_metrics_avro_to_metric_samples" {
    to_table = "posthog.metric_samples1"
    query    = file("sql/kafka_metrics_avro_to_metric_samples.sql")

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
    to_table = "posthog.metric_series1"
    query    = file("sql/kafka_metrics_avro_to_metric_series.sql")

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
}
