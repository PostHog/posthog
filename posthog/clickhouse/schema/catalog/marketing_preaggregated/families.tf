module "sharded_conversion_goal_attributed_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "conversion_goal_attributed_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_conversion_goal_attributed_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, person_id, conversion_timestamp, touchpoint_timestamp)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(person_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.conversion_goal_attributed_preaggregated"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_conversion_goal_attributed_preaggregated", "conversion_goal_attributed_preaggregated"], name) }
  })
  names = { storage = "sharded_conversion_goal_attributed_preaggregated" }
}

module "sharded_marketing_conversions_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "marketing_conversions_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_marketing_conversions_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, person_id, conversion_timestamp)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(person_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.marketing_conversions_preaggregated"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_marketing_conversions_preaggregated", "marketing_conversions_preaggregated"], name) }
  })
  names = { storage = "sharded_marketing_conversions_preaggregated" }
}

module "sharded_marketing_costs_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "marketing_costs_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_marketing_costs_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, source_name, grain, campaign_id, ad_group_id, ad_id, cost_date)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(source_name, campaign_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.marketing_costs_preaggregated"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_marketing_costs_preaggregated", "marketing_costs_preaggregated"], name) }
  })
  names = { storage = "sharded_marketing_costs_preaggregated" }
}

module "sharded_marketing_touchpoints_preaggregated_family" {
  source = "../../lib/table_family"

  name     = "marketing_touchpoints_preaggregated"
  database = var.database
  layout   = "global"
  columns  = local.sharded_marketing_touchpoints_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, person_id, touchpoint_timestamp)"
    ttl          = var.ttl ? "expires_at" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    read = true
  }
  sharding_key = "cityHash64(person_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.marketing_touchpoints_preaggregated"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_marketing_touchpoints_preaggregated", "marketing_touchpoints_preaggregated"], name) }
  })
  names = { storage = "sharded_marketing_touchpoints_preaggregated" }
}
