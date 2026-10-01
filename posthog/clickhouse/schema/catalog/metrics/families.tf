module "metric_attributes_family" {
  source = "../../lib/table_family"

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
  routing = {
    read  = false
    write = false
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.metric_attributes"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_attributes"], name) }
  })
  names = { storage = "metric_attributes" }
}

module "metric_attributes2_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_attributes2", "metric_attributes_distributed"], name) }
  })
  names = { storage = "metric_attributes2" }
}

module "metric_attributes3_family" {
  source = "../../lib/table_family"

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
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_attributes3"], name) }
  })
}

module "metric_names3_family" {
  source = "../../lib/table_family"

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
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_names3"], name) }
  })
}

module "metric_samples1_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_samples1", "metric_samples"], name) }
  })
  names = { storage = "metric_samples1" }
}

module "metric_series1_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_series1", "metric_series"], name) }
  })
  names = { storage = "metric_series1" }
}

module "metric_series2_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_series2", "metric_series_distributed"], name) }
  })
  names = { storage = "metric_series2" }
}

module "metric_series3_family" {
  source = "../../lib/table_family"

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
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metric_series3"], name) }
  })
}

module "metrics1_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics1", "metrics"], name) }
  })
  names = { storage = "metrics1" }
}

module "metrics2_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster      = "posthog"
    read_cluster = "posthog_single_shard"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics2", "metrics_distributed"], name) }
  })
  names = { storage = "metrics2" }
}

module "metrics4_attributes_family" {
  source = "../../lib/table_family"

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
    ]
  }
  routing = {
    write = true
  }
  sharding_key = ""
  deployment = merge({
    cluster       = "logs"
    write_cluster = "logs"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics4_attributes", "writable_metrics4_attributes"], name) }
  })
}

module "metrics4_names_family" {
  source = "../../lib/table_family"

  name     = "metrics4_names"
  database = var.database
  layout   = "global"
  columns  = local.metric_names3_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, time_bucket, metric_name, original_expiry_time_bucket)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
  }
  routing = {
    write = true
  }
  sharding_key = ""
  deployment = merge({
    cluster       = "logs"
    write_cluster = "logs"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics4_names", "writable_metrics4_names"], name) }
  })
}

module "metrics4_samples_family" {
  source = "../../lib/table_family"

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
  sharding_key = ""
  deployment = merge({
    cluster       = "logs"
    write_cluster = "logs"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics4_samples", "writable_metrics4_samples"], name) }
  })
}

module "metrics4_series_family" {
  source = "../../lib/table_family"

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
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
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
  sharding_key = ""
  deployment = merge({
    cluster       = "logs"
    write_cluster = "logs"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics4_series", "writable_metrics4_series"], name) }
  })
}

module "metrics_kafka_metrics_family" {
  source = "../../lib/table_family"

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
  routing = {
    read  = false
    write = false
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.metrics_kafka_metrics"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["metrics_kafka_metrics"], name) }
  })
  names = { storage = "metrics_kafka_metrics" }
}
