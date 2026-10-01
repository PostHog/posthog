# Tables that hold data, and the materialized views between them.

module "cohort_membership" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "cohort_membership")
  database = var.database
  name     = "cohort_membership"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.cohort_membership${var.zk_path_suffix}', '{replica}-{shard}', last_updated)"
  order_by = "(team_id, cohort_id, person_id)"
  columns  = local.cohort_membership_columns
  override = try(var.overrides["cohort_membership"], {})
}
