# Tables that hold data, and the materialized views between them.

module "sharded_conversion_goal_attributed_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_conversion_goal_attributed_preaggregated")
  database     = var.database
  name         = "sharded_conversion_goal_attributed_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.conversion_goal_attributed_preaggregated${var.zk_path_suffix}', '{replica}-{shard}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, person_id, conversion_timestamp, touchpoint_timestamp)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_conversion_goal_attributed_preaggregated_columns
  override     = try(var.overrides["sharded_conversion_goal_attributed_preaggregated"], {})
}

module "sharded_marketing_conversions_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_marketing_conversions_preaggregated")
  database     = var.database
  name         = "sharded_marketing_conversions_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.marketing_conversions_preaggregated${var.zk_path_suffix}', '{replica}-{shard}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, person_id, conversion_timestamp)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_marketing_conversions_preaggregated_columns
  override     = try(var.overrides["sharded_marketing_conversions_preaggregated"], {})
}

module "sharded_marketing_costs_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_marketing_costs_preaggregated")
  database     = var.database
  name         = "sharded_marketing_costs_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.marketing_costs_preaggregated${var.zk_path_suffix}', '{replica}-{shard}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, source_name, grain, campaign_id, ad_group_id, ad_id, cost_date)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_marketing_costs_preaggregated_columns
  override     = try(var.overrides["sharded_marketing_costs_preaggregated"], {})
}

module "sharded_marketing_touchpoints_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_marketing_touchpoints_preaggregated")
  database     = var.database
  name         = "sharded_marketing_touchpoints_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.marketing_touchpoints_preaggregated${var.zk_path_suffix}', '{replica}-{shard}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, person_id, touchpoint_timestamp)"
  ttl          = var.ttl ? "expires_at" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_marketing_touchpoints_preaggregated_columns
  override     = try(var.overrides["sharded_marketing_touchpoints_preaggregated"], {})
}
