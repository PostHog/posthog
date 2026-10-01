# Distributed tables that inserts go through.

module "writable_person_distinct_id2" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_person_distinct_id2")
  database = var.database
  name     = "writable_person_distinct_id2"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'person_distinct_id2')"
  columns  = local.person_distinct_id2_columns
  override = try(var.overrides["writable_person_distinct_id2"], {})
}
