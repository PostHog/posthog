# Tables that hold data, and the materialized views between them.

module "sharded_billing_usage_records" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_billing_usage_records")
  database     = var.database
  name         = "sharded_billing_usage_records"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_billing_usage_records${var.zk_path_suffix}', '{replica}', inserted_at)"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, toDate(timestamp), producer_id, usage_key, record_id)"
  columns      = local.sharded_billing_usage_records_columns
  override     = try(var.overrides["sharded_billing_usage_records"], {})
}
