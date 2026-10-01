# Tables that hold data, and the materialized views between them.

module "groups" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "groups")
  database = var.database
  name     = "groups"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.groups${var.zk_path_suffix}', '{replica}-{shard}', _timestamp)"
  order_by = "(team_id, group_type_index, group_key)"
  columns = concat(local.writable_groups_columns, [
    { name = "is_deleted", type = "Bool" },
  ])
  indexes = [
    { name = "is_deleted_idx", expression = "is_deleted", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["groups"], {})
}
