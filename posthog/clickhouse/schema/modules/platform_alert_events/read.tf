# Distributed tables, views and dictionaries that queries read from.

module "platform_alert_events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "platform_alert_events")
  database = var.database
  name     = "platform_alert_events"
  engine   = "Distributed('aux', '${var.database}', 'sharded_platform_alert_events', cityHash64(team_id))"
  columns  = local.sharded_platform_alert_events_columns
  override = try(var.overrides["platform_alert_events"], {})
}
