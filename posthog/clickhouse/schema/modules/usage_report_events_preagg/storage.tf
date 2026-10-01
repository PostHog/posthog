# Tables that hold data, and the materialized views between them.

module "sharded_usage_report_events_preagg" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_usage_report_events_preagg")
  database     = var.database
  name         = "sharded_usage_report_events_preagg"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_usage_report_events_preagg${var.zk_path_suffix}', '{replica}')"
  partition_by = "date"
  order_by     = "(date, team_id, person_mode, lib, event)"
  ttl          = var.ttl ? "date + toIntervalDay(14)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_usage_report_events_preagg_columns
  override     = try(var.overrides["sharded_usage_report_events_preagg"], {})
}
