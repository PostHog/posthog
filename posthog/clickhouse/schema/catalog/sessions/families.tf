module "sharded_sessions_family" {
  source = "../../lib/table_family"

  name     = "sessions"
  database = var.database
  columns  = local.sharded_sessions_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toYYYYMM(min_timestamp)"
    order_by     = "(toStartOfDay(min_timestamp), team_id, session_id)"
    settings     = "index_granularity = 512"
  }
  sharding_key = "sipHash64(session_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.sessions"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_sessions", "sessions", "writable_sessions"], name) }
  })
}
