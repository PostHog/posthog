# Column lists that more than one object uses.

locals {
  kafka_app_metrics2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "app_source", type = "LowCardinality(String)" },
    { name = "app_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "metric_kind", type = "String" },
    { name = "metric_name", type = "String" },
    { name = "count", type = "Int64" },
  ]

  sharded_app_metrics2_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "app_source", type = "LowCardinality(String)" },
    { name = "app_source_id", type = "String" },
    { name = "instance_id", type = "String" },
    { name = "metric_kind", type = "LowCardinality(String)" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "count", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]

  sharded_app_metrics_columns = [
    { name = "team_id", type = "Int64" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "plugin_config_id", type = "Int64" },
    { name = "category", type = "LowCardinality(String)" },
    { name = "job_id", type = "String" },
    { name = "successes", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "successes_on_retry", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "failures", type = "SimpleAggregateFunction(sum, Int64)" },
    { name = "error_uuid", type = "UUID" },
    { name = "error_type", type = "String" },
    { name = "error_details", type = "String", codec = "ZSTD(3)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
}
