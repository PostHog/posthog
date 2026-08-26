# Objects common to the local logs node and every cloud logs env — the base the
# whole role composes. Env deltas (the logs cluster vs the local single-shard
# cluster, per-shard zk paths, prod settings) are patch_table blocks in the env
# layers, never second definitions.

database "posthog" {

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

  materialized_view "logs34_to_volume_buckets" {
    to_table = "posthog.logs_volume_buckets"
    query    = file("sql/logs34_to_volume_buckets.sql")

    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type = "DateTime('UTC')"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "namespace" {
      type = "LowCardinality(String)"
    }
    column "environment" {
      type = "LowCardinality(String)"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "log_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
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

  table "log_attributes2" {
    order_by     = ["team_id", "attribute_type", "time_bucket", "resource_fingerprint", "attribute_key", "attribute_value"]
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.log_attributes2"
      replica_name = "{replica}-{shard}"
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
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "log_attributes3"
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs_billing_metrics"
      replica_name = "{replica}-{shard}"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs_billing_metrics"
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
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs34"
    }
  }

  table "logs_kafka_metrics" {
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs_kafka_metrics"
      replica_name = "{replica}-{shard}"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs_kafka_metrics"
    }
  }

  table "logs_volume_buckets" {
    order_by     = ["team_id", "time_bucket", "service_name", "namespace", "environment", "severity_text"]
    partition_by = "toDate(time_bucket)"
    ttl          = "time_bucket + toIntervalDay(42)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type  = "DateTime('UTC')"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "namespace" {
      type = "LowCardinality(String)"
    }
    column "environment" {
      type = "LowCardinality(String)"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "log_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.logs_volume_buckets"
      replica_name = "{replica}-{shard}"
    }
  }

  table "logs_volume_buckets_distributed" {
    column "team_id" {
      type = "Int32"
    }
    column "time_bucket" {
      type  = "DateTime('UTC')"
      codec = "DoubleDelta, ZSTD(1)"
    }
    column "service_name" {
      type = "LowCardinality(String)"
    }
    column "namespace" {
      type = "LowCardinality(String)"
    }
    column "environment" {
      type = "LowCardinality(String)"
    }
    column "severity_text" {
      type = "LowCardinality(String)"
    }
    column "log_count" {
      type = "SimpleAggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "logs_volume_buckets"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "metric_samples1"
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
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "metric_series1"
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
    column "pattern" {
      type = "String"
    }
    column "pattern_version" {
      type = "UInt8"
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
    projection "projection_aggregate_counts" {
      query = <<SQL
SELECT
  team_id,
  time_bucket,
  toStartOfMinute(timestamp),
  service_name,
  severity_text,
  resource_fingerprint,
  count() AS event_count
GROUP BY
  team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint
SQL

    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/logs/{shard}/posthog.logs34"
      replica_name = "{replica}"
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
