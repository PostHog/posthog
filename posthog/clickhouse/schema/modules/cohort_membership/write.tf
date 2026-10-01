# Distributed tables that inserts go through.

module "writable_cohort_membership" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_cohort_membership")
  database = var.database
  name     = "writable_cohort_membership"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'cohort_membership')"
  columns  = local.cohort_membership_columns
  override = try(var.overrides["writable_cohort_membership"], {})
}
