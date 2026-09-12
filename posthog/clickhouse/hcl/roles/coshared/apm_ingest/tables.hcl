# The Kafka ingest for metrics and traces: the consumers and the views that
# drain them. dev runs this on its ingestion-apm nodes, the prod clusters on
# their logs nodes, so it sits here rather than inside either role.
database "posthog" {
  table "kafka_metrics_avro" {
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
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }

  materialized_view "kafka_metrics_avro_kafka_metrics_mv" {
    to_table = "posthog.metrics_kafka_metrics"
    query = file("sql/kafka_metrics_avro_kafka_metrics_mv.sql")
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
    to_table = "posthog.metrics1"
    query = file("sql/kafka_metrics_avro_mv.sql")
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

  table "kafka_trace_spans_avro" {
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
      num_consumers        = 8
      skip_broken_messages = 100
      poll_timeout_ms      = 3000
      poll_max_batch_size  = 1000
      thread_per_consumer  = true
    }
  }

  materialized_view "kafka_trace_spans_avro_mv" {
    to_table = "posthog.trace_spans"
    query = file("sql/kafka_trace_spans_avro_mv.sql")
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
    column "service_name" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "attributes_map_str" {
      type = "Map(LowCardinality(String), String)"
    }
    column "dropped_attributes_count" {
      type = "UInt32"
    }
    column "events" {
      type = "Array(String)"
    }
    column "dropped_events_count" {
      type = "UInt32"
    }
    column "links" {
      type = "Array(String)"
    }
    column "dropped_links_count" {
      type = "UInt32"
    }
    column "status_code" {
      type = "Int16"
    }
    column "team_id" {
      type = "Int32"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
  }
}
