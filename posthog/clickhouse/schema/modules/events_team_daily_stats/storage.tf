# Tables that hold data, and the materialized views between them.

module "events_team_daily_stats" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "events_team_daily_stats")
  database = var.database
  name     = "events_team_daily_stats"
  engine   = "ReplicatedMergeTree('/clickhouse/ops/tables/{shard}/posthog.events_team_daily_stats${var.zk_path_suffix}', '{replica}')"
  order_by = "(analysis_date, team_id, event)"
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
  override = try(var.overrides["events_team_daily_stats"], {})
}
