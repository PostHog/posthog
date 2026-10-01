# Tables that hold data, and the materialized views between them.

module "person_static_cohort" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "person_static_cohort")
  database = var.database
  name     = "person_static_cohort"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_static_cohort${var.zk_path_suffix}', '{replica}-{shard}', _timestamp)"
  order_by = "(team_id, cohort_id, person_id, id)"
  columns = [
    { name = "id", type = "UUID" },
    { name = "person_id", type = "UUID" },
    { name = "cohort_id", type = "Int64" },
    { name = "team_id", type = "Int64" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
  override = try(var.overrides["person_static_cohort"], {})
}
