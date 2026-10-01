# Distributed tables that inserts go through.

module "writable_metrics4_attributes" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_metrics4_attributes")
  database = var.database
  name     = "writable_metrics4_attributes"
  engine   = "Distributed('logs', '${var.database}', 'metrics4_attributes')"
  columns  = local.metric_attributes3_columns
  override = try(var.overrides["writable_metrics4_attributes"], {})
}

module "writable_metrics4_names" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_metrics4_names")
  database = var.database
  name     = "writable_metrics4_names"
  engine   = "Distributed('logs', '${var.database}', 'metrics4_names')"
  columns  = local.metric_names3_columns
  override = try(var.overrides["writable_metrics4_names"], {})
}

module "writable_metrics4_samples" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_metrics4_samples")
  database = var.database
  name     = "writable_metrics4_samples"
  engine   = "Distributed('logs', '${var.database}', 'metrics4_samples')"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime" },
    { name = "series_fingerprint", type = "UInt64" },
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
    { name = "timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))" },
    { name = "observed_timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))" },
    { name = "value_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Float64))" },
    { name = "count_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64))" },
    { name = "histogram_counts_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64)))" },
    { name = "trace_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "span_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "trace_flags_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))" },
  ]
  override = try(var.overrides["writable_metrics4_samples"], {})
}

module "writable_metrics4_series" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_metrics4_series")
  database = var.database
  name     = "writable_metrics4_series"
  engine   = "Distributed('logs', '${var.database}', 'metrics4_series')"
  columns = [
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
  override = try(var.overrides["writable_metrics4_series"], {})
}
