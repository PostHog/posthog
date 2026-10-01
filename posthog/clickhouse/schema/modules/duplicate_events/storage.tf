# Tables that hold data, and the materialized views between them.

module "duplicate_events" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "duplicate_events")
  database     = var.database
  name         = "duplicate_events"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.duplicate_events${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMMDD(inserted_at)"
  order_by     = "(team_id, distinct_id, event, inserted_at)"
  ttl          = var.ttl ? "inserted_at + toIntervalDay(7)" : null
  settings     = "index_granularity = 512"
  columns      = local.duplicate_events_columns
  indexes = [
    { name = "kafka_timestamp_minmax_duplicate_events", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["duplicate_events"], {})
}
