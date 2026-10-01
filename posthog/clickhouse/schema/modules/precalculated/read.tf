# Distributed tables, views and dictionaries that queries read from.

module "precalculated_events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "precalculated_events")
  database = var.database
  name     = "precalculated_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_precalculated_events', sipHash64(distinct_id))"
  columns  = local.sharded_precalculated_events_columns
  override = try(var.overrides["precalculated_events"], {})
}

module "precalculated_person_properties" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "precalculated_person_properties")
  database = var.database
  name     = "precalculated_person_properties"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_precalculated_person_properties', sipHash64(distinct_id))"
  columns  = local.sharded_precalculated_person_properties_columns
  override = try(var.overrides["precalculated_person_properties"], {})
}
