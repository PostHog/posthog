# Distributed tables that inserts go through.

module "writable_events_recent" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_events_recent")
  database = var.database
  name     = "writable_events_recent"
  engine   = "Distributed('posthog_writable', '${var.database}', 'sharded_events_recent', sipHash64(distinct_id))"
  columns  = local.writable_events_recent_columns
  override = try(var.overrides["writable_events_recent"], {})
}
