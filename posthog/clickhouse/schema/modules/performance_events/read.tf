# Distributed tables, views and dictionaries that queries read from.

module "performance_events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "performance_events")
  database = var.database
  name     = "performance_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_performance_events', sipHash64(session_id))"
  columns  = local.sharded_performance_events_columns
  override = try(var.overrides["performance_events"], {})
}
