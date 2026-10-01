# Tables that hold data, and the materialized views between them.

module "sharded_app_metrics" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_app_metrics")
  database     = var.database
  name         = "sharded_app_metrics"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_app_metrics${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, plugin_config_id, job_id, category, toStartOfHour(timestamp), error_type, error_uuid)"
  columns      = local.sharded_app_metrics_columns
  override     = try(var.overrides["sharded_app_metrics"], {})
}

module "sharded_app_metrics2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_app_metrics2")
  database     = var.database
  name         = "sharded_app_metrics2"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_app_metrics2${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, app_source, app_source_id, instance_id, toStartOfHour(timestamp), metric_kind, metric_name)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  columns      = local.sharded_app_metrics2_columns
  override     = try(var.overrides["sharded_app_metrics2"], {})
}
