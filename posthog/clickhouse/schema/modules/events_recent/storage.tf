# Tables that hold data, and the materialized views between them.

module "events_recent_json_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "events_recent_json_mv")
  database = var.database
  name     = "events_recent_json_mv"
  to_table = "${var.database}.writable_events_recent"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        properties,
        timestamp,
        team_id,
        distinct_id,
        elements_chain,
        created_at,
        person_id,
        person_created_at,
        person_properties,
        group0_properties,
        group1_properties,
        group2_properties,
        group3_properties,
        group4_properties,
        group0_created_at,
        group1_created_at,
        group2_created_at,
        group3_created_at,
        group4_created_at,
        person_mode,
        _timestamp,
        _offset
    FROM ${var.database}.sharded_events
  SQL
  override = try(var.overrides["events_recent_json_mv"], {})

  depends_on = [
    module.writable_events_recent,
  ]
}

module "sharded_events_recent" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_events_recent")
  database     = var.database
  name         = "sharded_events_recent"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_events_recent${var.zk_path_suffix}', '{replica}', _timestamp)"
  partition_by = "toStartOfDay(inserted_at)"
  order_by     = "(team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))"
  ttl          = var.ttl ? "toDate(inserted_at) + toIntervalDay(9)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_events_recent_columns
  override     = try(var.overrides["sharded_events_recent"], {})
}
