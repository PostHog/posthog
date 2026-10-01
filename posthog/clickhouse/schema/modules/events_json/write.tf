# Distributed tables that inserts go through.

module "writable_events_json" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_events_json")
  database = var.database
  name     = "writable_events_json"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_events_json', sipHash64(distinct_id))"
  columns  = local.writable_events_json_columns
  override = try(var.overrides["writable_events_json"], {})
}
