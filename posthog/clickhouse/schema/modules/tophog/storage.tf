# Tables that hold data, and the materialized views between them.

module "sharded_tophog" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_tophog")
  database     = var.database
  name         = "sharded_tophog"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.tophog${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(pipeline, lane, metric, timestamp, key)"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(30)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_tophog_columns
  override     = try(var.overrides["sharded_tophog"], {})
}
