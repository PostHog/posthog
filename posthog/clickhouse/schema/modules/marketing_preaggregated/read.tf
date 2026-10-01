# Distributed tables, views and dictionaries that queries read from.

module "conversion_goal_attributed_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "conversion_goal_attributed_preaggregated")
  database = var.database
  name     = "conversion_goal_attributed_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_conversion_goal_attributed_preaggregated', cityHash64(person_id))"
  columns  = local.sharded_conversion_goal_attributed_preaggregated_columns
  override = try(var.overrides["conversion_goal_attributed_preaggregated"], {})
}

module "marketing_conversions_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "marketing_conversions_preaggregated")
  database = var.database
  name     = "marketing_conversions_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_marketing_conversions_preaggregated', cityHash64(person_id))"
  columns  = local.sharded_marketing_conversions_preaggregated_columns
  override = try(var.overrides["marketing_conversions_preaggregated"], {})
}

module "marketing_costs_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "marketing_costs_preaggregated")
  database = var.database
  name     = "marketing_costs_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_marketing_costs_preaggregated', cityHash64(source_name, campaign_id))"
  columns  = local.sharded_marketing_costs_preaggregated_columns
  override = try(var.overrides["marketing_costs_preaggregated"], {})
}

module "marketing_touchpoints_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "marketing_touchpoints_preaggregated")
  database = var.database
  name     = "marketing_touchpoints_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_marketing_touchpoints_preaggregated', cityHash64(person_id))"
  columns  = local.sharded_marketing_touchpoints_preaggregated_columns
  override = try(var.overrides["marketing_touchpoints_preaggregated"], {})
}
