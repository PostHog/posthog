# Distributed tables, views and dictionaries that queries read from.

module "usage_report_events_preagg" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "usage_report_events_preagg")
  database = var.database
  name     = "usage_report_events_preagg"
  engine   = "Distributed('aux', '${var.database}', 'sharded_usage_report_events_preagg', sipHash64(date))"
  columns  = local.sharded_usage_report_events_preagg_columns
  override = try(var.overrides["usage_report_events_preagg"], {})
}
