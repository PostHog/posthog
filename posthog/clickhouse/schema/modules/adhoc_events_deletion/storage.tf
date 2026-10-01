# Tables that hold data, and the materialized views between them.

module "adhoc_events_deletion" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "adhoc_events_deletion")
  database = var.database
  name     = "adhoc_events_deletion"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.adhoc_events_deletion${var.zk_path_suffix}', '{replica}-{shard}', deleted_at, is_deleted)"
  order_by = "(team_id, uuid)"
  ttl      = var.ttl ? "deleted_at + toIntervalMonth(3) WHERE is_deleted = 1" : null
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "uuid", type = "UUID" },
    { name = "data_deletion_request_id", type = "Nullable(UUID)" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
    { name = "deleted_at", type = "DateTime" },
    { name = "is_deleted", type = "UInt8", default_expression = "0" },
  ]
  override = try(var.overrides["adhoc_events_deletion"], {})
}
