# Tables that hold data, and the materialized views between them.

module "person" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "person")
  database = var.database
  name     = "person"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, id)"
  columns  = local.person_columns
  indexes = [
    { name = "kafka_timestamp_minmax_person", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  unmanaged_columns = ["^p?mat_"]
  unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"]
  override          = try(var.overrides["person"], {})
}
