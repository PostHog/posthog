# Tables that hold data, and the materialized views between them.

module "llma_metrics_daily" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "llma_metrics_daily")
  database     = var.database
  name         = "llma_metrics_daily"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.llma_metrics_daily${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(date)"
  order_by     = "(team_id, date, metric_name)"
  columns = [
    { name = "date", type = "Date" },
    { name = "team_id", type = "UInt64" },
    { name = "metric_name", type = "String" },
    { name = "metric_value", type = "Float64" },
  ]
  override = try(var.overrides["llma_metrics_daily"], {})
}
