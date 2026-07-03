# LOGS role — managed logs/traces/metrics objects extracted from *-logs.hcl dumps.
database "posthog" {
  view "custom_metrics" {
    query = file("sql/custom_metrics.sql")
  }
  materialized_view "kafka_logs_avro_kafka_metrics_mv" {
    to_table = "posthog.logs_kafka_metrics"
    query = file("sql/kafka_logs_avro_kafka_metrics_mv.sql")
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
      broker_list          = "warpstream_metrics"
      topic_list           = "kafka_topic_list = 'clickhouse_metrics'"
      group_name           = "kafka_group_name = 'clickhouse-metrics-avro-new'"
      format               = "kafka_format = 'Avro'"
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
  table "log_attributes2" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(time_bucket)"
    ttl          = "time_bucket + toIntervalDay(15)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
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
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/log_attributes34"
      replica_name = "{replica}"
    }
  }
  materialized_view "logs34_to_log_attributes" {
    to_table = "posthog.log_attributes2"
    query = file("sql/logs34_to_log_attributes.sql")
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
    column "resource_fingerprint" {
      type = "UInt64"
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
  materialized_view "logs34_to_resource_attributes" {
    to_table = "posthog.log_attributes2"
    query = file("sql/logs34_to_resource_attributes.sql")
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
    column "resource_fingerprint" {
      type = "UInt64"
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
  table "logs_billing_metrics" {
    order_by     = ["team_id", "time_bucket", "service_name"]
    partition_by = "toYYYYMM(time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_billing_metrics"
      replica_name = "{replica}"
    }
  }
  table "logs_billing_metrics_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime64(0)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "bytes_uncompressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "bytes_compressed" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "record_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "logs"
      remote_database = "posthog"
      remote_table    = "logs_billing_metrics"
    }
  }
  table "logs_kafka_metrics" {
    order_by = ["_topic", "_partition"]
    settings = {
      deduplicate_merge_projection_mode = "rebuild"
      index_granularity                 = "8192"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/logs_kafka_metrics"
      replica_name = "{replica}"
    }
  }
  table "logs_kafka_metrics_distributed" {
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
      remote_table    = "logs_kafka_metrics"
    }
  }
  table "metric_attributes" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
    partition_by = "toDate(time_bucket)"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
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
      type = "String"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    column "attribute_type" {
      type = "LowCardinality(String)"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.metric_attributes"
      replica_name = "{replica}"
    }
  }
  materialized_view "metrics1_to_metric_attributes" {
    to_table = "posthog.metric_attributes"
    query = file("sql/metrics1_to_metric_attributes.sql")
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
      type = "UInt64"
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
  materialized_view "metrics1_to_resource_attributes" {
    to_table = "posthog.metric_attributes"
    query = file("sql/metrics1_to_resource_attributes.sql")
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
      type = "UInt64"
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
  table "metrics_kafka_metrics" {
    order_by = ["_topic", "_partition"]
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.metrics_kafka_metrics"
      replica_name = "{replica}"
    }
  }
  table "log_attributes3" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value", "severity_text"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      deduplicate_merge_projection_mode = "drop"
      index_granularity                 = "8192"
    }
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
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    index "idx_attribute_key" {
      expr        = "attribute_key"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_value" {
      expr        = "attribute_value"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attribute_key_n3" {
      expr        = "attribute_key"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    index "idx_attribute_value_n3" {
      expr        = "attribute_value"
      type        = "ngrambf_v1(3, 32768, 3, 0)"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes3"
      replica_name = "{replica}-{shard}"
    }
  }
  table "metric_samples" {
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
  table "metric_samples1" {
    order_by     = ["team_id", "metric_name", "series_fingerprint", "timestamp"]
    partition_by = "toDate(timestamp)"
    ttl          = "toDateTime(timestamp) + toIntervalDay(30)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
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
    index "idx_trace_id_bf" {
      expr        = "trace_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metric_samples1"
      replica_name = "{replica}-{shard}"
    }
  }
  table "metric_series" {
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
  table "metric_series1" {
    order_by = ["team_id", "metric_name", "series_fingerprint"]
    ttl      = "toDateTime(last_seen) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
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
    index "idx_service_set" {
      expr        = "service_name"
      type        = "set(1000)"
      granularity = 1
    }
    index "idx_attr_keys" {
      expr        = "mapKeys(attributes)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_attr_values" {
      expr        = "mapValues(attributes)"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.metric_series1"
      replica_name   = "{replica}-{shard}"
      version_column = "last_seen"
    }
  }
  materialized_view "logs34_to_log_attributes3" {
    to_table = "posthog.log_attributes3"
    query    = file("sql/logs34_to_log_attributes3.sql")

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
    column "resource_fingerprint" {
      type = "UInt64"
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
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
  }
  materialized_view "logs34_to_resource_attributes3" {
    to_table = "posthog.log_attributes3"
    query    = file("sql/logs34_to_resource_attributes3.sql")

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
    column "resource_fingerprint" {
      type = "UInt64"
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
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "attribute_count" {
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
}
