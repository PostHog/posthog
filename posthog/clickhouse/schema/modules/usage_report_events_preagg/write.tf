# Distributed tables that inserts go through.

module "writable_usage_report_events_preagg" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_usage_report_events_preagg")
  database = var.database
  name     = "writable_usage_report_events_preagg"
  engine   = "Distributed('aux', '${var.database}', 'sharded_usage_report_events_preagg', sipHash64(date))"
  columns  = local.sharded_usage_report_events_preagg_columns
  override = try(var.overrides["writable_usage_report_events_preagg"], {})
}
