module "property_definitions" {
  source  = "../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "property_definitions"
  database = var.database
  layout   = "global"
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, type, coalesce(event, ''), name, coalesce(group_type_index, 255))"
  }
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
  deployment = merge(var.deployment.global, try(var.deployment.families.property_definitions, {}), { overrides = var.overrides })
}
