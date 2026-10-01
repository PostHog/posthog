# Distributed tables that inserts go through.

module "writable_person_distinct_id_overrides" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_person_distinct_id_overrides")
  database = var.database
  name     = "writable_person_distinct_id_overrides"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'person_distinct_id_overrides')"
  columns  = local.person_distinct_id_overrides_columns
  override = try(var.overrides["writable_person_distinct_id_overrides"], {})
}
