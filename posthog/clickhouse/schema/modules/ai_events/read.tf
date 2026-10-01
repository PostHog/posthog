# Distributed tables, views and dictionaries that queries read from.

module "ai_events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "ai_events")
  database = var.database
  name     = "ai_events"
  engine   = "Distributed('ai_events', '${var.database}', 'sharded_ai_events', cityHash64(concat(toString(team_id), '-', trace_id, '-', toString(toDate(timestamp)))))"
  columns  = local.sharded_ai_events_columns
  override = try(var.overrides["ai_events"], {})
}
