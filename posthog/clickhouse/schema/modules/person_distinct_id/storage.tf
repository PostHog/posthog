# Tables that hold data, and the materialized views between them.

module "person_distinct_id" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "person_distinct_id")
  database = var.database
  name     = "person_distinct_id"
  engine   = "ReplicatedCollapsingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id${var.zk_path_suffix}', '{replica}-{shard}', _sign)"
  order_by = "(team_id, distinct_id, person_id)"
  columns = [
    { name = "distinct_id", type = "String", comment = "skip_0003_fill_person_distinct_id2" },
    { name = "person_id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "_sign", type = "Int8", default_expression = "1" },
    { name = "is_deleted", type = "Int8", alias_expression = "if(_sign = -1, 1, 0)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
  override = try(var.overrides["person_distinct_id"], {})
}

module "person_distinct_id2" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "person_distinct_id2")
  database = var.database
  name     = "person_distinct_id2"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id2${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, distinct_id)"
  settings = "index_granularity = 512"
  columns  = local.person_distinct_id2_columns
  indexes = [
    { name = "kafka_timestamp_minmax_person_distinct_id2", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["person_distinct_id2"], {})
}
