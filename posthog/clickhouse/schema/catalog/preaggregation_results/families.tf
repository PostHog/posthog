module "sharded_preaggregation_results_family" {
  source = "../../lib/table_family"

  name     = "preaggregation_results"
  database = var.database
  columns  = local.sharded_preaggregation_results_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(time_window_start)"
    order_by     = "(team_id, job_id, time_window_start, breakdown_value)"
    ttl          = var.ttl ? "expires_at" : null
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.preaggregation_results"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_preaggregation_results", "preaggregation_results"], name) }
  })
}
