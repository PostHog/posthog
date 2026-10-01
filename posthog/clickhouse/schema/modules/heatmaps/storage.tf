# Tables that hold data, and the materialized views between them.

module "sharded_heatmaps" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_heatmaps")
  database     = var.database
  name         = "sharded_heatmaps"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.heatmaps${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(type, team_id, toDate(timestamp), current_url, viewport_width)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  columns      = local.sharded_heatmaps_columns
  override     = try(var.overrides["sharded_heatmaps"], {})
}
