# Tables that hold data, and the materialized views between them.

module "property_definitions" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "property_definitions")
  database = var.database
  name     = "property_definitions"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.property_definitions${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id, type, coalesce(event, ''), name, coalesce(group_type_index, 255))"
  columns = [
    { name = "team_id", type = "UInt32" },
    { name = "project_id", type = "Nullable(UInt32)" },
    { name = "name", type = "String" },
    { name = "property_type", type = "Nullable(String)" },
    { name = "event", type = "Nullable(String)" },
    { name = "group_type_index", type = "Nullable(UInt8)" },
    { name = "type", type = "UInt8", default_expression = "1" },
    { name = "last_seen_at", type = "DateTime" },
    { name = "version", type = "UInt64", materialized_expression = "bitShiftLeft(toUInt64(NOT isNull(property_type)), 48) + toUInt64(toUnixTimestamp(last_seen_at))" },
  ]
  override = try(var.overrides["property_definitions"], {})
}
