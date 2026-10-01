# Distributed tables that inserts go through.

module "writable_precalculated_events" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_precalculated_events")
  database = var.database
  name     = "writable_precalculated_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_precalculated_events', sipHash64(distinct_id))"
  columns  = local.sharded_precalculated_events_columns
  override = try(var.overrides["writable_precalculated_events"], {})
}

module "writable_precalculated_person_properties" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_precalculated_person_properties")
  database = var.database
  name     = "writable_precalculated_person_properties"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_precalculated_person_properties', sipHash64(distinct_id))"
  columns  = local.sharded_precalculated_person_properties_columns
  override = try(var.overrides["writable_precalculated_person_properties"], {})
}
