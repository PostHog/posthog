# Tables that hold data, and the materialized views between them.

module "sharded_preaggregation_results" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_preaggregation_results")
  database     = var.database
  name         = "sharded_preaggregation_results"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.preaggregation_results${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(time_window_start)"
  order_by     = "(team_id, job_id, time_window_start, breakdown_value)"
  ttl          = var.ttl ? "expires_at" : null
  columns      = local.sharded_preaggregation_results_columns
  override     = try(var.overrides["sharded_preaggregation_results"], {})
}
