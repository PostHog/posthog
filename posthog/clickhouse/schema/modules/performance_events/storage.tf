# Tables that hold data, and the materialized views between them.

module "sharded_performance_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_performance_events")
  database     = var.database
  name         = "sharded_performance_events"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.performance_events${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, toDate(timestamp), session_id, pageview_id, timestamp)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalWeek(3)" : null
  columns      = local.sharded_performance_events_columns
  override     = try(var.overrides["sharded_performance_events"], {})
}
