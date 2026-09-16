database "posthog" {
  table "metric_names3" {
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = ["team_id", "time_bucket", "metric_name", "original_expiry_time_bucket"]
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.metric_names3"
      replica_name = "{replica}-{shard}"
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
  table "metric_series3" {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by = ["team_id", "metric_name", "series_fingerprint"]
    ttl      = "original_expiry_timestamp"
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
    column "last_seen" {
      type = "DateTime64(6)"
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
    index "idx_last_seen_minmax" {
      expr        = "last_seen"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.metric_series3"
      replica_name   = "{replica}-{shard}"
      version_column = "last_seen"
    }
  }
  table "metric_attributes3" {
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
      zoo_path     = "/clickhouse/tables/noshard/posthog.metric_attributes3"
      replica_name = "{replica}-{shard}"
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
