# Tables that hold data, and the materialized views between them.

module "property_values" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "property_values")
  database = var.database
  name     = "property_values"
  engine   = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.property_values${var.zk_path_suffix}', '{replica}-{shard}')"
  order_by = "(team_id, property_type, property_key, property_value)"
  ttl      = var.ttl ? "last_seen + toIntervalDay(30)" : null
  columns  = local.property_values_columns
  indexes = [
    { name = "idx_property_value_ngrambf", expression = "lower(property_value)", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["property_values"], {})
}
