database "posthog" {
  materialized_view "kafka_metrics_avro2_mv" {
    to_table = "posthog.metrics2_input"
    query    = file("sql/kafka_metrics_avro2_mv.sql")
    column "uuid" {
      type = "String"
    }
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "String"
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
      type = "String"
    }
    column "aggregation_temporality" {
      type = "String"
    }
    column "is_monotonic" {
      type = "UInt8"
    }
    column "instrumentation_scope" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(String, String)"
    }
    column "attributes" {
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
  }
  materialized_view "metrics2_input_to_metrics" {
    to_table = "posthog.metrics2"
    query    = file("sql/metrics2_input_to_metrics.sql")
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
    column "_partition" {
      type = "UInt32"
    }
    column "_topic" {
      type = "String"
    }
    column "_offset" {
      type = "UInt64"
    }
  }
  materialized_view "metrics2_input_to_metric_series" {
    to_table = "posthog.metric_series2"
    query    = file("sql/metrics2_input_to_metric_series.sql")
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type = "UInt64"
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
      type = "Bool"
    }
    column "service_name" {
      type = "LowCardinality(String)"
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
    column "last_seen" {
      type = "DateTime64(6)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
  }
  materialized_view "metrics2_input_to_metric_attributes" {
    to_table = "posthog.metric_attributes2"
    query    = file("sql/metrics2_input_to_metric_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
  materialized_view "metrics2_input_to_resource_attributes" {
    to_table = "posthog.metric_attributes2"
    query    = file("sql/metrics2_input_to_resource_attributes.sql")
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
  materialized_view "metrics2_input_to_metric_names3" {
    to_table = "posthog.metric_names3"
    query    = file("sql/metrics2_input_to_metric_names3.sql")
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_timestamp" {
      type = "SimpleAggregateFunction(max, DateTime64(6))"
    }
  }
  materialized_view "metrics2_input_to_metric_series3" {
    to_table = "posthog.metric_series3"
    query    = file("sql/metrics2_input_to_metric_series3.sql")
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "series_fingerprint" {
      type = "UInt64"
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
      type = "Bool"
    }
    column "service_name" {
      type = "LowCardinality(String)"
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
    column "last_seen" {
      type = "DateTime64(6)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
  }
  materialized_view "metrics2_input_to_metric_attributes3" {
    to_table = "posthog.metric_attributes3"
    query    = file("sql/metrics2_input_to_metric_attributes3.sql")
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
  materialized_view "metrics2_input_to_resource_attributes3" {
    to_table = "posthog.metric_attributes3"
    query    = file("sql/metrics2_input_to_resource_attributes3.sql")
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "original_expiry_time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type = "String"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
}
