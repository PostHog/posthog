# LOGS role, cloud only — the Kafka metrics ingest MVs. Env-identical across dev /
# prod-us / prod-eu (all read the WarpStream metrics_avro topic straight into the
# metric_samples1 / metric_series1 tables). The local node has no metrics ingest.
# The ZK-path and codec deltas the two prods share sit in roles/logs/prod.

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

  # Only the cloud envs carry the logs Kafka ingest on the logs role: their events nodes are
  # authored in posthog-cloud-infra. The local envs carry it on the ingestion_events role.
  table "kafka_logs_avro" {
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
    engine "kafka" {
      broker_list          = "warpstream_logs"
      topic_list           = "kafka_topic_list = 'clickhouse_logs'"
      group_name           = "kafka_group_name = 'clickhouse-logs-avro-new'"
      format               = "kafka_format = 'Avro'"
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
}
