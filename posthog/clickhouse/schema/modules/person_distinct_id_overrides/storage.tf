# Tables that hold data, and the materialized views between them.

module "person_distinct_id_overrides" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "person_distinct_id_overrides")
  database = var.database
  name     = "person_distinct_id_overrides"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id_overrides${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, distinct_id)"
  settings = "index_granularity = 512"
  columns  = local.person_distinct_id_overrides_columns
  indexes = [
    { name = "kafka_timestamp_minmax_person_distinct_id_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["person_distinct_id_overrides"], {})
}
