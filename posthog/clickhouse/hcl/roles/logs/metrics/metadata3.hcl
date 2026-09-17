database "posthog" {
  table "metric_series3" {
    extend = "_metric_series3_columns"
    partition_by = "toDate(original_expiry_timestamp)"
    order_by = ["team_id", "metric_name", "series_fingerprint"]
    ttl      = "original_expiry_timestamp"
    settings = {
      index_granularity = "8192"
    }
    patch_column "series_fingerprint" {
      codec = "Delta(8), Default"
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
    extend = "_metric_attributes3_columns"
    order_by     = ["team_id", "metric_name", "attribute_type", "time_bucket", "attribute_key", "attribute_value", "service_name", "original_expiry_time_bucket"]
    partition_by = "toDate(original_expiry_time_bucket)"
    ttl          = "original_expiry_time_bucket"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
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
  table "metric_names3" {
    extend = "_metric_names3_columns"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = ["team_id", "time_bucket", "metric_name", "original_expiry_time_bucket"]
    ttl          = "original_expiry_timestamp"
    settings = {
      index_granularity = "8192"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.metric_names3"
      replica_name = "{replica}-{shard}"
    }
  }
}
