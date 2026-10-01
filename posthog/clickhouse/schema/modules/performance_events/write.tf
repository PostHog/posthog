# Distributed tables that inserts go through.

module "writeable_performance_events" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writeable_performance_events")
  database = var.database
  name     = "writeable_performance_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_performance_events', sipHash64(session_id))"
  columns  = local.sharded_performance_events_columns
  override = try(var.overrides["writeable_performance_events"], {})
}
