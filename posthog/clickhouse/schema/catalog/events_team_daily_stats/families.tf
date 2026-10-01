module "events_team_daily_stats_family" {
  source = "../../lib/table_family"

  name     = "events_team_daily_stats"
  database = var.database
  columns = [
    { name = "analysis_date", type = "Date" },
    { name = "team_id", type = "Int64" },
    { name = "event", type = "String" },
    { name = "event_count", type = "UInt64" },
    { name = "total_event_bytes", type = "UInt64" },
    { name = "min_event_bytes", type = "UInt64" },
    { name = "max_event_bytes", type = "UInt64" },
    { name = "avg_event_bytes", type = "Float64" },
    { name = "p50_event_bytes", type = "Float64" },
    { name = "p90_event_bytes", type = "Float64" },
    { name = "p95_event_bytes", type = "Float64" },
    { name = "p99_event_bytes", type = "Float64" },
    { name = "event_size_histogram", type = "Array(Tuple(Float64, Float64, UInt64))" },
    { name = "computed_at", type = "DateTime" },
  ]
  storage = {
    order_by = "(analysis_date, team_id, event)"
  }
  routing = {
    read  = false
    write = false
  }
  deployment = merge({
    keeper_path = "/clickhouse/ops/tables/{shard}/${var.database}.events_team_daily_stats"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["events_team_daily_stats"], name) }
  })
  names = { storage = "events_team_daily_stats" }
}
