variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

# Column lists that more than one object uses.

locals {
  sharded_marketing_touchpoints_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "person_id", type = "UUID" },
    { name = "touchpoint_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "campaign_name", type = "String" },
    { name = "source_name", type = "String" },
    { name = "medium_name", type = "String" },
    { name = "content_name", type = "String" },
    { name = "term_name", type = "String" },
    { name = "referring_domain_name", type = "String" },
    { name = "gclid_name", type = "String" },
    { name = "fbclid_name", type = "String" },
    { name = "gad_source_name", type = "String" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]

  sharded_marketing_conversions_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "person_id", type = "UUID" },
    { name = "conversion_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "conversion_math_value", type = "Float64" },
    { name = "session_id", type = "String" },
    { name = "campaign_name", type = "String" },
    { name = "source_name", type = "String" },
    { name = "medium_name", type = "String" },
    { name = "content_name", type = "String" },
    { name = "term_name", type = "String" },
    { name = "referring_domain_name", type = "String" },
    { name = "gclid_name", type = "String" },
    { name = "fbclid_name", type = "String" },
    { name = "gad_source_name", type = "String" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]

  sharded_conversion_goal_attributed_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "person_id", type = "UUID" },
    { name = "conversion_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "conversion_value", type = "Float64" },
    { name = "touchpoint_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "touchpoint_weight", type = "Float64" },
    { name = "campaign_name", type = "String" },
    { name = "source_name", type = "String" },
    { name = "medium_name", type = "String" },
    { name = "content_name", type = "String" },
    { name = "term_name", type = "String" },
    { name = "referring_domain_name", type = "String" },
    { name = "gclid_name", type = "String" },
    { name = "fbclid_name", type = "String" },
    { name = "gad_source_name", type = "String" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]

  sharded_marketing_costs_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "source_id", type = "String" },
    { name = "source_name", type = "String" },
    { name = "grain", type = "LowCardinality(String)" },
    { name = "match_key", type = "String" },
    { name = "campaign_id", type = "String" },
    { name = "campaign_name", type = "String" },
    { name = "ad_group_id", type = "String" },
    { name = "ad_group_name", type = "String" },
    { name = "ad_id", type = "String" },
    { name = "ad_name", type = "String" },
    { name = "cost_date", type = "Date" },
    { name = "cost", type = "Float64" },
    { name = "clicks", type = "Float64" },
    { name = "impressions", type = "Float64" },
    { name = "reported_conversions", type = "Float64" },
    { name = "reported_conversion_value", type = "Float64" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "Date", default_expression = "today() + toIntervalDay(7)" },
  ]
}

module "sharded_conversion_goal_attributed_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
  names = { storage = "sharded_conversion_goal_attributed_preaggregated" }
}

module "sharded_marketing_conversions_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
  names = { storage = "sharded_marketing_conversions_preaggregated" }
}

module "sharded_marketing_costs_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
  names = { storage = "sharded_marketing_costs_preaggregated" }
}

module "sharded_marketing_touchpoints_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  }, local.deployment)
  names = { storage = "sharded_marketing_touchpoints_preaggregated" }
}
