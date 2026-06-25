# LOGS dev overlay — env-specific / differing logs objects.
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
  table "log_attributes_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "resource_fingerprint" {
      type    = "UInt64"
      default = "0"
    }
    column "attribute_key" {
      type = "LowCardinality(String)"
    }
    column "attribute_value" {
      type  = "String"
      codec = "ZSTD(5)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type    = "LowCardinality(String)"
      default = "'log'"
    }
    column "original_expiry_time_bucket" {
      type    = "DateTime"
      default = "now()"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "log_attributes2"
    }
  }
  table "logs34" {
    order_by     = ["team_id", "time_bucket", "service_name", "resource_fingerprint", "severity_text", "timestamp"]
    partition_by = "toDate(original_expiry_timestamp)"
    ttl          = "original_expiry_timestamp"
    settings = {
      add_minmax_index_for_numeric_columns = "1"
      allow_experimental_reverse_key       = "1"
      index_granularity                    = "8192"
      index_granularity_bytes              = "104857600"
      map_serialization_version            = "with_buckets"
      ttl_only_drop_parts                  = "1"
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
    index "idx_severity_text_set" {
      expr        = "severity_text"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_mat_body_ipv4_matches" {
      expr        = "mat_body_ipv4_matches"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_body_ngram3" {
      expr        = "lower(body)"
      type        = "ngrambf_v1(3, 25000, 2, 0)"
      granularity = 1
    }
    index "idx_uuid_bloom" {
      expr        = "uuid"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.logs34"
      replica_name = "{replica}"
    }
  }
  table "logs_distributed" {
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
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }
  table "metrics" {
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
  table "metrics1" {
    order_by     = ["team_id", "time_bucket", "service_name", "metric_name", "resource_fingerprint", "timestamp"]
    partition_by = "toDate(timestamp)"
    settings = {
      index_granularity       = "8192"
      index_granularity_bytes = "104857600"
      ttl_only_drop_parts     = "1"
    }
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
    index "idx_metric_name_set" {
      expr        = "metric_name"
      type        = "set(100)"
      granularity = 1
    }
    index "idx_metric_type_set" {
      expr        = "metric_type"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_attributes_str_keys" {
      expr        = "mapKeys(attributes_map_str)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attributes_str_values" {
      expr        = "mapValues(attributes_map_str)"
      type        = "bloom_filter(0.001)"
      granularity = 1
    }
    index "idx_observed_minmax" {
      expr        = "observed_timestamp"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.metrics1"
      replica_name = "{replica}"
    }
  }
}
