# Tables that hold data, and the materialized views between them.

module "ingestion_warnings_v2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "ingestion_warnings_v2")
  database     = var.database
  name         = "ingestion_warnings_v2"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.ingestion_warnings_v2${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, type, timestamp)"
  ttl          = var.ttl ? "toDateTime(timestamp) + toIntervalDay(90)" : null
  columns      = local.ingestion_warnings_v2_columns
  override     = try(var.overrides["ingestion_warnings_v2"], {})
}

module "sharded_ingestion_warnings" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_ingestion_warnings")
  database     = var.database
  name         = "sharded_ingestion_warnings"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.sharded_ingestion_warnings${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMMDD(timestamp)"
  order_by     = "(team_id, toHour(timestamp), type, source, timestamp)"
  columns      = local.sharded_ingestion_warnings_columns
  override     = try(var.overrides["sharded_ingestion_warnings"], {})
}
