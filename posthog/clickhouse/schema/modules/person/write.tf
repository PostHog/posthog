# Distributed tables that inserts go through.

module "writable_person" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_person")
  database = var.database
  name     = "writable_person"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'person')"
  columns  = local.person_columns
  override = try(var.overrides["writable_person"], {})
}
