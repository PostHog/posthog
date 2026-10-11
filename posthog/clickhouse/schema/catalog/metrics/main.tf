variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {
}

# Column lists that more than one object uses.

locals {
  metric_names3_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)" },
    { name = "original_expiry_timestamp", type = "SimpleAggregateFunction(max, DateTime64(6))" },
  ]

  metric_attributes2_columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String" },
    { name = "attribute_type", type = "LowCardinality(String)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  metric_attributes3_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String" },
    { name = "attribute_type", type = "LowCardinality(String)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  metric_samples1_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64", codec = "DoubleDelta" },
    { name = "timestamp", type = "DateTime64(6)", codec = "DoubleDelta" },
    { name = "value", type = "Float64", codec = "Gorilla(8)" },
    { name = "count", type = "UInt64", default_expression = "1" },
    { name = "histogram_bounds", type = "Array(Float64)" },
    { name = "histogram_counts", type = "Array(UInt64)" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Int32" },
  ]

  metric_series1_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64", codec = "DoubleDelta" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)" },
    { name = "last_seen", type = "DateTime64(6)", codec = "DoubleDelta" },
  ]

  metric_series2_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)" },
    { name = "last_seen", type = "DateTime64(6)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
  ]

  kafka_metrics_avro4_columns = [
    { name = "uuid", type = "String" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Nullable(Int32)" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "service_name", type = "Nullable(String)" },
    { name = "metric_name", type = "Nullable(String)" },
    { name = "metric_type", type = "Nullable(String)" },
    { name = "value", type = "Nullable(Float64)" },
    { name = "count", type = "Nullable(Int64)" },
    { name = "histogram_bounds", type = "Array(Float64)" },
    { name = "histogram_counts", type = "Array(Int64)" },
    { name = "unit", type = "Nullable(String)" },
    { name = "aggregation_temporality", type = "Nullable(String)" },
    { name = "is_monotonic", type = "Nullable(UInt8)" },
    { name = "resource_attributes", type = "Map(String, String)" },
    { name = "instrumentation_scope", type = "Nullable(String)" },
    { name = "attributes", type = "Map(String, String)" },
    { name = "series_fingerprint", type = "Nullable(Int64)" },
    { name = "has_labels", type = "Nullable(UInt8)" },
    { name = "retention_days", type = "Nullable(Int32)" },
  ]

  metrics1_columns = [
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfDay(timestamp)" },
    { name = "uuid", type = "String" },
    { name = "team_id", type = "Int32" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Int32" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "created_at", type = "DateTime64(6)", materialized_expression = "now()" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "value", type = "Float64", codec = "Gorilla(8)" },
    { name = "count", type = "UInt64", default_expression = "1", codec = "T64" },
    { name = "histogram_bounds", type = "Array(Float64)" },
    { name = "histogram_counts", type = "Array(UInt64)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "attributes_map_str", type = "Map(LowCardinality(String), String)" },
    { name = "attributes_map_float", type = "Map(LowCardinality(String), Float64)" },
    { name = "time_minute", type = "DateTime", alias_expression = "toStartOfMinute(timestamp)" },
    { name = "attributes", type = "Map(String, String)", alias_expression = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)" },
  ]

  metrics2_columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfHour(timestamp)" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0" },
    { name = "timestamp", type = "DateTime64(6)", codec = "DoubleDelta" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
    { name = "created_at", type = "DateTime64(6)", materialized_expression = "now()" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "value", type = "Float64", codec = "Gorilla(8)" },
    { name = "count", type = "UInt64", default_expression = "1", codec = "T64" },
    { name = "histogram_bounds", type = "Array(Float64)" },
    { name = "histogram_counts", type = "Array(UInt64)" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Int32" },
    { name = "has_labels", type = "Bool", default_expression = "false" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "instrumentation_scope", type = "String" },
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "_offset", type = "UInt64" },
  ]

  metrics4_input_columns = [
    { name = "uuid", type = "String" },
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64" },
    { name = "resource_fingerprint", type = "UInt64" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "value", type = "Float64" },
    { name = "count", type = "UInt64" },
    { name = "histogram_bounds", type = "Array(Float64)" },
    { name = "histogram_counts", type = "Array(UInt64)" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "trace_flags", type = "Int32" },
    { name = "has_labels", type = "Bool" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool" },
    { name = "instrumentation_scope", type = "String" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)" },
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "_offset", type = "UInt64" },
  ]
}

module "metric_attributes_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_attributes"
  database = var.database
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "attribute_type", type = "LowCardinality(String)" },
  ]
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  deployment = merge({ replica_name = "{replica}" }, local.deployment)
  layout     = "global"
}

module "metric_attributes2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_attributes_distributed"
  database = var.database
  layout   = "global"
  columns  = local.metric_attributes2_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  routing = {
    read = true
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "metric_attributes2" }
}

module "metric_attributes3_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_attributes3"
  database = var.database
  layout   = "global"
  columns  = local.metric_attributes3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  deployment = local.deployment
}

module "metric_names3_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_names3"
  database = var.database
  layout   = "global"
  columns  = local.metric_names3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, time_bucket, metric_name, original_expiry_time_bucket)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
  }
  deployment = local.deployment
}

module "metric_samples1_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_samples"
  database = var.database
  layout   = "global"
  columns  = local.metric_samples1_columns
  storage = {
    partition_by = "toDate(timestamp)"
    order_by     = "(team_id, metric_name, series_fingerprint, timestamp)"
    ttl          = var.ttl ? "toDateTime(timestamp) + toIntervalDay(30)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_trace_id_bf", expression = "trace_id", type = "bloom_filter(0.01)", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    read_columns = local.metric_samples1_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "metric_samples1" }
}

module "metric_series1_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_series"
  database = var.database
  layout   = "global"
  columns  = local.metric_series1_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["last_seen"]
    order_by    = "(team_id, metric_name, series_fingerprint)"
    ttl         = var.ttl ? "toDateTime(last_seen) + toIntervalDay(90)" : null
    indexes = [
      { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
      { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    read_columns = local.metric_series1_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "metric_series1" }
}

module "metric_series2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_series_distributed"
  database = var.database
  layout   = "global"
  columns  = local.metric_series2_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["last_seen"]
    order_by    = "(team_id, metric_name, series_fingerprint)"
    ttl         = var.ttl ? "original_expiry_timestamp" : null
    indexes = [
      { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
      { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_last_seen_minmax", expression = "last_seen", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    read_columns = local.metric_series2_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "metric_series2" }
}

module "metric_series3_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metric_series3"
  database = var.database
  layout   = "global"
  columns  = local.metric_series2_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["last_seen"]
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, metric_name, series_fingerprint)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    indexes = [
      { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
      { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_last_seen_minmax", expression = "last_seen", type = "minmax", granularity = 1 },
    ]
  }
  deployment = local.deployment
}

module "metrics1_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics"
  database = var.database
  columns  = local.metrics1_columns
  storage = {
    partition_by = "toDate(timestamp)"
    order_by     = "(team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)"
    settings     = "index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_metric_name_set", expression = "metric_name", type = "set(100)", granularity = 1 },
      { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
      { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
      { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
    ]
    projections = [
      { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint, count() AS event_count, sum(value) AS total_value, min(value) AS min_value, max(value) AS max_value GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint" },
    ]
  }
  routing = {
    write        = false
    read_columns = local.metrics1_columns
  }
  sharding_key = ""
  deployment = merge({
    keeper_path  = "/clickhouse/tables/noshard/${var.database}.metrics1"
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
  }, local.deployment)
  names = { storage = "metrics1" }
}

module "metrics2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics_distributed"
  database = var.database
  layout   = "global"
  columns  = local.metrics2_columns
  storage = {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, metric_name, time_bucket, series_fingerprint, timestamp)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    settings     = "index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
      { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
      { name = "idx_trace_id_bf", expression = "trace_id", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
      { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
    ]
    projections = [
      { name = "projection_series_activity", query = "SELECT team_id, service_name, metric_name, metric_type, resource_fingerprint, series_fingerprint, toStartOfHour(timestamp) AS hour, count() AS sample_count, max(timestamp) AS last_seen GROUP BY team_id, service_name, metric_name, metric_type, resource_fingerprint, series_fingerprint, hour" },
    ]
  }
  routing = {
    read         = true
    read_columns = local.metrics2_columns
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "metrics2" }
}

module "metrics4_attributes_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics4_attributes"
  database = var.database
  layout   = "global"
  columns  = local.metric_attributes3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
      { name = "idx_time_bucket_minmax", expression = "time_bucket", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    write = true
  }
  deployment = merge({ cluster = "logs", write_cluster = "logs" }, local.deployment)
}

module "metrics4_names_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics4_names"
  database = var.database
  layout   = "global"
  columns  = concat(local.metric_names3_columns, [{ name = "service_name", type = "LowCardinality(String)" }])
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
  }
  routing = {
    write = true
  }
  deployment = merge({ cluster = "logs", write_cluster = "logs" }, local.deployment)
}

module "metrics4_samples_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics4_samples"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "original_expiry_date", type = "Date32" },
    { name = "resource_fingerprint", type = "SimpleAggregateFunction(any, UInt64)" },
    { name = "service_name", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "metric_type", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "unit", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "aggregation_temporality", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "is_monotonic", type = "SimpleAggregateFunction(max, UInt8)" },
    { name = "has_labels", type = "SimpleAggregateFunction(max, UInt8)" },
    { name = "instrumentation_scope", type = "SimpleAggregateFunction(any, String)" },
    { name = "histogram_bounds", type = "SimpleAggregateFunction(anyLast, Array(Float64))" },
    { name = "_topic", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))", codec = "DoubleDelta, Default" },
    { name = "observed_timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))", codec = "DoubleDelta, Default" },
    { name = "value_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Float64))", codec = "Gorilla(8), Default" },
    { name = "count_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64))", codec = "T64, Default" },
    { name = "histogram_counts_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64)))", codec = "T64, Default" },
    { name = "trace_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "span_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "trace_flags_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))" },
    { name = "timestamp_min", type = "DateTime64(6)", alias_expression = "arrayMin(timestamp_arr)" },
    { name = "timestamp_max", type = "DateTime64(6)", alias_expression = "arrayMax(timestamp_arr)" },
  ]
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "original_expiry_date"
    order_by     = "(team_id, metric_name, time_bucket, series_fingerprint)"
    ttl          = var.ttl ? "original_expiry_date" : null
    settings     = "index_granularity = 128, ttl_only_drop_parts = 1"
    indexes = [
      { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
      { name = "idx_time_bucket_minmax", expression = "time_bucket", type = "minmax", granularity = 1 },
      { name = "idx_trace_id_bf", expression = "trace_id_arr", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_timestamp_min_minmax", expression = "timestamp_min", type = "minmax", granularity = 1 },
      { name = "idx_timestamp_max_minmax", expression = "timestamp_max", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    write = true
  }
  deployment = merge({ cluster = "logs", write_cluster = "logs" }, local.deployment)
}

module "metrics4_series_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics4_series"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfHour(timestamp)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["timestamp"]
    partition_by = "toStartOfWeek(original_expiry_timestamp)"
    order_by     = "(team_id, metric_name, series_fingerprint, time_bucket)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1, deduplicate_merge_projection_mode = 'rebuild'"
    projections = [{
      name  = "services_by_hour"
      query = "SELECT team_id, time_bucket, service_name, uniqExact(metric_name), uniq(series_fingerprint), max(timestamp) GROUP BY team_id, time_bucket, service_name"
    }]
    indexes = [
      { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
      { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
      { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
      { name = "idx_time_bucket_minmax", expression = "time_bucket", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    write = true
    write_columns = [
      { name = "team_id", type = "Int32" },
      { name = "metric_name", type = "LowCardinality(String)" },
      { name = "series_fingerprint", type = "UInt64" },
      { name = "metric_type", type = "LowCardinality(String)" },
      { name = "unit", type = "LowCardinality(String)" },
      { name = "aggregation_temporality", type = "LowCardinality(String)" },
      { name = "is_monotonic", type = "Bool", default_expression = "false" },
      { name = "service_name", type = "LowCardinality(String)" },
      { name = "instrumentation_scope", type = "String" },
      { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
      { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
      { name = "attributes", type = "Map(LowCardinality(String), String)" },
      { name = "timestamp", type = "DateTime64(6)" },
      { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfHour(timestamp)" },
      { name = "original_expiry_timestamp", type = "DateTime64(6)" },
    ]
  }
  deployment = merge({ cluster = "logs", write_cluster = "logs" }, local.deployment)
}

module "metrics_kafka_metrics_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "metrics_kafka_metrics"
  database = var.database
  columns = [
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "max_offset", type = "SimpleAggregateFunction(max, UInt64)" },
    { name = "max_observed_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_created_at", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_lag", type = "SimpleAggregateFunction(max, UInt64)" },
  ]
  storage = {
    engine   = "AggregatingMergeTree"
    order_by = "(_topic, _partition)"
  }
  deployment = merge({ replica_name = "{replica}" }, local.deployment)
  layout     = "global"
}

# Tables that hold data, and the materialized views between them.

module "metrics4_input" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "metrics4_input")
  database = var.database
  name     = "metrics4_input"
  engine   = "`Null`"
  columns  = local.metrics4_input_columns
  override = try(local.deployment.overrides["metrics4_input"], {})
}

module "metrics4_input_to_metrics4_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics4_input_to_metrics4_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_attributes_family,
  ]
}

module "metrics4_input_to_metrics4_names" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics4_input_to_metrics4_names")
  database = var.database
  name     = "metrics4_input_to_metrics4_names"
  to_table = "${var.database}.writable_metrics4_names"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toStartOfHour(timestamp) AS time_bucket,
        toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
        maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp,
        service_name
    FROM ${var.database}.metrics4_input AS input
    WHERE has_labels
    GROUP BY
        team_id,
        time_bucket,
        metric_name,
        original_expiry_time_bucket,
        service_name
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_names"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_names_family,
  ]
}

module "metrics4_input_to_metrics4_resource_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics4_input_to_metrics4_resource_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_resource_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_resource_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_attributes_family,
  ]
}

module "metrics4_input_to_metrics4_samples" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics4_input_to_metrics4_samples")
  database = var.database
  name     = "metrics4_input_to_metrics4_samples"
  to_table = "${var.database}.writable_metrics4_samples"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toDateTime(toStartOfHour(timestamp)) AS time_bucket,
        series_fingerprint,
        toDate32(original_expiry_timestamp) AS original_expiry_date,
        any(resource_fingerprint) AS resource_fingerprint,
        any(service_name) AS service_name,
        any(metric_type) AS metric_type,
        any(unit) AS unit,
        any(aggregation_temporality) AS aggregation_temporality,
        max(toUInt8(is_monotonic)) AS is_monotonic,
        max(toUInt8(has_labels)) AS has_labels,
        any(instrumentation_scope) AS instrumentation_scope,
        anyLast(histogram_bounds) AS histogram_bounds,
        any(_topic) AS _topic,
        groupArray(10000)(timestamp) AS timestamp_arr,
        groupArray(10000)(observed_timestamp) AS observed_timestamp_arr,
        groupArray(10000)(value) AS value_arr,
        groupArray(10000)(count) AS count_arr,
        groupArray(10000)(histogram_counts) AS histogram_counts_arr,
        groupArray(10000)(trace_id) AS trace_id_arr,
        groupArray(10000)(span_id) AS span_id_arr,
        groupArray(10000)(trace_flags) AS trace_flags_arr
    FROM ${var.database}.metrics4_input
    GROUP BY
        team_id,
        metric_name,
        time_bucket,
        series_fingerprint,
        original_expiry_date
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_samples"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_samples_family,
  ]
}

module "metrics4_input_to_metrics4_series" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "metrics4_input_to_metrics4_series")
  database = var.database
  name     = "metrics4_input_to_metrics4_series"
  to_table = "${var.database}.writable_metrics4_series"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp,
        original_expiry_timestamp
    FROM ${var.database}.metrics4_input
    WHERE has_labels
  SQL
  override = try(local.deployment.overrides["metrics4_input_to_metrics4_series"], {})

  depends_on = [
    module.metrics4_input,
    module.metrics4_series_family,
  ]
}

# Distributed tables, views and dictionaries that queries read from.

module "metrics4_view" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "metrics4_view")
  database = var.database
  name     = "metrics4_view"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        series_fingerprint,
        resource_fingerprint,
        timestamp,
        observed_timestamp,
        original_expiry_timestamp,
        service_name,
        metric_type,
        value,
        count,
        histogram_bounds,
        histogram_counts,
        trace_id,
        span_id,
        trace_flags,
        has_labels,
        unit,
        aggregation_temporality,
        is_monotonic,
        instrumentation_scope
    FROM ${var.database}.metrics2
    WHERE (time_bucket > toDateTime('2026-08-25 00:00:00')) AND (time_bucket < toDateTime('2026-09-14 00:00:00')) AND (timestamp > toDateTime('2026-08-25 00:00:00')) AND (timestamp < toDateTime('2026-09-14 00:00:00'))
    UNION ALL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        series_fingerprint,
        resource_fingerprint,
        point_timestamp AS timestamp,
        point_observed_timestamp AS observed_timestamp,
        toDateTime64(original_expiry_date, 6) AS original_expiry_timestamp,
        service_name,
        metric_type,
        point_value AS value,
        point_count AS count,
        histogram_bounds,
        point_histogram_counts AS histogram_counts,
        point_trace_id AS trace_id,
        point_span_id AS span_id,
        point_trace_flags AS trace_flags,
        toBool(has_labels) AS has_labels,
        unit,
        aggregation_temporality,
        toBool(is_monotonic) AS is_monotonic,
        instrumentation_scope
    FROM ${var.database}.metrics4_samples
    ARRAY JOIN
        timestamp_arr AS point_timestamp,
        observed_timestamp_arr AS point_observed_timestamp,
        value_arr AS point_value,
        count_arr AS point_count,
        histogram_counts_arr AS point_histogram_counts,
        trace_id_arr AS point_trace_id,
        span_id_arr AS point_span_id,
        trace_flags_arr AS point_trace_flags
    WHERE time_bucket >= toDateTime('2026-09-14 00:00:00')
  SQL
  override = try(local.deployment.overrides["metrics4_view"], {})

  depends_on = [
    module.metrics2_family,
    module.metrics4_samples_family,
  ]
}

# Kafka tables and the materialized views that consume them.

module "kafka_metrics_avro4" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_metrics_avro4")
  database = var.database
  name     = "kafka_metrics_avro4"
  engine   = "Kafka(warpstream_metrics)"
  settings = "input_format_avro_allow_missing_fields = 1, kafka_format = 'Avro', kafka_group_name = 'clickhouse-metrics-avro4', kafka_num_consumers = 1, kafka_poll_max_batch_size = 1000, kafka_poll_timeout_ms = 3000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_metrics'"
  columns  = local.kafka_metrics_avro4_columns
  override = try(local.deployment.overrides["kafka_metrics_avro4"], {})
}

module "kafka_metrics_avro4_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "kafka_metrics_avro4_mv")
  database = var.database
  name     = "kafka_metrics_avro4_mv"
  to_table = "${var.database}.metrics4_input"
  query    = <<-SQL
    SELECT
        uuid,
        toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
        ifNull(metric_name, '') AS metric_name,
        reinterpretAsUInt64(assumeNotNull(series_fingerprint)) AS series_fingerprint,
        cityHash64(mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes))) AS resource_fingerprint,
        timestamp,
        observed_timestamp,
        timestamp + toIntervalDay(assumeNotNull(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(30))))) AS original_expiry_timestamp,
        ifNull(service_name, '') AS service_name,
        ifNull(metric_type, '') AS metric_type,
        ifNull(value, 0) AS value,
        toUInt64(ifNull(count, 1)) AS count,
        histogram_bounds,
        arrayMap(x -> toUInt64(x), histogram_counts) AS histogram_counts,
        trace_id,
        span_id,
        ifNull(trace_flags, 0) AS trace_flags,
        toBool(ifNull(has_labels, 1)) AS has_labels,
        ifNull(unit, '') AS unit,
        ifNull(aggregation_temporality, '') AS aggregation_temporality,
        ifNull(is_monotonic, 0) AS is_monotonic,
        ifNull(instrumentation_scope, '') AS instrumentation_scope,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)), CAST(map(), 'Map(String, String)')) AS resource_attributes,
        if(toBool(ifNull(has_labels, 1)), mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), attributes)), CAST(map(), 'Map(String, String)')) AS attributes,
        _partition,
        _topic,
        _offset
    FROM ${var.database}.kafka_metrics_avro4
    WHERE kafka_metrics_avro4.series_fingerprint IS NOT NULL
    SETTINGS min_insert_block_size_rows = 0, min_insert_block_size_bytes = 0
  SQL
  override = try(local.deployment.overrides["kafka_metrics_avro4_mv"], {})

  depends_on = [
    module.kafka_metrics_avro4,
    module.metrics4_input,
  ]
}
