# These tables store hourly data from metrics4_input.
# metrics4_samples stores each sample field in a parallel array.
# Each sample row stores at most 10,000 points for one series-hour.
# The other tables store series, name, and attribute data.
# posthog/clickhouse/metrics/metrics4.py defines the source schema.
database "posthog" {
  table "metrics4_attributes" {
    order_by     = ["team_id", "metric_name", "attribute_type", "time_bucket", "attribute_key", "attribute_value", "service_name", "original_expiry_time_bucket"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics4_attributes"
      replica_name = "{replica}-{shard}"
    }
  }

  table "metrics4_names" {
    order_by     = ["team_id", "time_bucket", "metric_name", "original_expiry_time_bucket"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_timestamp"
    settings = {
      index_granularity = "8192"
    }
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics4_names"
      replica_name = "{replica}-{shard}"
    }
  }

  table "metrics4_samples" {
    order_by     = ["team_id", "metric_name", "time_bucket", "series_fingerprint"]
    partition_by = "original_expiry_date"
    ttl          = "original_expiry_date"
    settings = {
      index_granularity   = "128"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int32"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "time_bucket" {
      type = "DateTime"
    }
    column "series_fingerprint" {
      type  = "UInt64"
      codec = "Delta(8), Default"
    }
    column "original_expiry_date" {
      type = "Date32"
    }
    column "resource_fingerprint" {
      type = "SimpleAggregateFunction(any, UInt64)"
    }
    column "service_name" {
      type = "SimpleAggregateFunction(any, LowCardinality(String))"
    }
    column "metric_type" {
      type = "SimpleAggregateFunction(any, LowCardinality(String))"
    }
    column "unit" {
      type = "SimpleAggregateFunction(any, LowCardinality(String))"
    }
    column "aggregation_temporality" {
      type = "SimpleAggregateFunction(any, LowCardinality(String))"
    }
    column "is_monotonic" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "has_labels" {
      type = "SimpleAggregateFunction(max, UInt8)"
    }
    column "instrumentation_scope" {
      type = "SimpleAggregateFunction(any, String)"
    }
    column "histogram_bounds" {
      type = "SimpleAggregateFunction(anyLast, Array(Float64))"
    }
    column "_topic" {
      type = "SimpleAggregateFunction(any, LowCardinality(String))"
    }
    column "timestamp_arr" {
      type  = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))"
      codec = "DoubleDelta, Default"
    }
    column "observed_timestamp_arr" {
      type  = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))"
      codec = "DoubleDelta, Default"
    }
    column "value_arr" {
      type  = "SimpleAggregateFunction(groupArrayArray(10000), Array(Float64))"
      codec = "Gorilla(8), Default"
    }
    column "count_arr" {
      type  = "SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64))"
      codec = "T64, Default"
    }
    column "histogram_counts_arr" {
      type  = "SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64)))"
      codec = "T64, Default"
    }
    column "trace_id_arr" {
      type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))"
    }
    column "span_id_arr" {
      type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))"
    }
    column "trace_flags_arr" {
      type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))"
    }
    column "timestamp_min" {
      type  = "DateTime64(6)"
      alias = "arrayMin(timestamp_arr)"
    }
    column "timestamp_max" {
      type  = "DateTime64(6)"
      alias = "arrayMax(timestamp_arr)"
    }
    index "idx_metric_type_set" {
      expr        = "metric_type"
      type        = "set(10)"
      granularity = 1
    }
    index "idx_time_bucket_minmax" {
      expr        = "time_bucket"
      type        = "minmax"
      granularity = 1
    }
    index "idx_trace_id_bf" {
      expr        = "trace_id_arr"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "idx_timestamp_min_minmax" {
      expr        = "timestamp_min"
      type        = "minmax"
      granularity = 1
    }
    index "idx_timestamp_max_minmax" {
      expr        = "timestamp_max"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metrics4_samples"
      replica_name = "{replica}-{shard}"
    }
  }

  table "metrics4_series" {
    order_by     = ["team_id", "metric_name", "series_fingerprint", "time_bucket"]
    partition_by = "toStartOfWeek(original_expiry_timestamp)"
    ttl          = "original_expiry_timestamp"
    settings = {
      index_granularity   = "1024"
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
      codec = "Delta(8), Default"
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
    column "instrumentation_scope" {
      type = "String"
    }
    column "resource_attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "resource_fingerprint" {
      type         = "UInt64"
      materialized = "cityHash64(resource_attributes)"
    }
    column "attributes" {
      type = "Map(LowCardinality(String), String)"
    }
    column "timestamp" {
      type = "DateTime64(6)"
    }
    column "time_bucket" {
      type         = "DateTime"
      materialized = "toStartOfHour(timestamp)"
    }
    column "original_expiry_timestamp" {
      type = "DateTime64(6)"
    }
    index "idx_service_set" {
      expr        = "service_name"
      type        = "set(1000)"
      granularity = 1
    }
    index "idx_resource_fingerprint" {
      expr        = "resource_fingerprint"
      type        = "bloom_filter(0.01)"
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
    index "idx_timestamp_minmax" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "idx_time_bucket_minmax" {
      expr        = "time_bucket"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.metrics4_series"
      replica_name   = "{replica}-{shard}"
      version_column = "timestamp"
    }
  }
}
