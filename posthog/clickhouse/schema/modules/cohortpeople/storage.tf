# Tables that hold data, and the materialized views between them.

module "cohortpeople" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "cohortpeople")
  database = var.database
  name     = "cohortpeople"
  engine   = "ReplicatedCollapsingMergeTree('/clickhouse/tables/noshard/posthog.cohortpeople${var.zk_path_suffix}', '{replica}-{shard}', sign)"
  order_by = "(team_id, cohort_id, person_id, version)"
  columns = [
    { name = "person_id", type = "UUID" },
    { name = "cohort_id", type = "Int64" },
    { name = "team_id", type = "Int64" },
    { name = "sign", type = "Int8" },
    { name = "version", type = "UInt64" },
  ]
  override = try(var.overrides["cohortpeople"], {})
}
