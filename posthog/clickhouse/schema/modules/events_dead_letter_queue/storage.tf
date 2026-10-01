# Tables that hold data, and the materialized views between them.

module "events_dead_letter_queue" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "events_dead_letter_queue")
  database = var.database
  name     = "events_dead_letter_queue"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.events_dead_letter_queue${var.zk_path_suffix}', '{replica}-{shard}', _timestamp)"
  order_by = "(id, event_uuid, distinct_id, team_id)"
  ttl      = var.ttl ? "toDate(_timestamp) + toIntervalWeek(4)" : null
  settings = "index_granularity = 512"
  columns  = local.events_dead_letter_queue_columns
  indexes = [
    { name = "kafka_timestamp_minmax_events_dead_letter_queue", expression = "_timestamp", type = "minmax", granularity = 3 },
  ]
  override = try(var.overrides["events_dead_letter_queue"], {})
}
