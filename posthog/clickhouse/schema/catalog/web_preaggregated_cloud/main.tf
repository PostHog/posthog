# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
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

module "web_bounces_daily_distributed" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "web_bounces_daily_distributed")
  database = var.database
  name     = "web_bounces_daily_distributed"
  override = try(local.deployment.overrides["web_bounces_daily_distributed"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'web_bounces_daily', rand())"
  columns = [
    { name = "period_bucket", type = "DateTime" },
    { name = "team_id", type = "UInt64" },
    { name = "host", type = "String" },
    { name = "device_type", type = "String" },
    { name = "entry_pathname", type = "String" },
    { name = "end_pathname", type = "String" },
    { name = "browser", type = "String" },
    { name = "os", type = "String" },
    { name = "viewport_width", type = "Int64" },
    { name = "viewport_height", type = "Int64" },
    { name = "referring_domain", type = "String" },
    { name = "utm_source", type = "String" },
    { name = "utm_medium", type = "String" },
    { name = "utm_campaign", type = "String" },
    { name = "utm_term", type = "String" },
    { name = "utm_content", type = "String" },
    { name = "country_code", type = "String" },
    { name = "city_name", type = "String" },
    { name = "region_code", type = "String" },
    { name = "region_name", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "bounces_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "total_session_duration_state", type = "AggregateFunction(sum, Int64)" },
    { name = "total_session_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]
}

module "web_bounces_hourly_distributed" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "web_bounces_hourly_distributed")
  database = var.database
  name     = "web_bounces_hourly_distributed"
  override = try(local.deployment.overrides["web_bounces_hourly_distributed"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'web_bounces_hourly', rand())"
  columns = [
    { name = "period_bucket", type = "DateTime" },
    { name = "team_id", type = "UInt64" },
    { name = "host", type = "String" },
    { name = "device_type", type = "String" },
    { name = "entry_pathname", type = "String" },
    { name = "end_pathname", type = "String" },
    { name = "browser", type = "String" },
    { name = "os", type = "String" },
    { name = "viewport_width", type = "Int64" },
    { name = "viewport_height", type = "Int64" },
    { name = "referring_domain", type = "String" },
    { name = "utm_source", type = "String" },
    { name = "utm_medium", type = "String" },
    { name = "utm_campaign", type = "String" },
    { name = "utm_term", type = "String" },
    { name = "utm_content", type = "String" },
    { name = "country_code", type = "String" },
    { name = "city_name", type = "String" },
    { name = "region_code", type = "String" },
    { name = "region_name", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "bounces_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "total_session_duration_state", type = "AggregateFunction(sum, Int64)" },
    { name = "total_session_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]
}

module "web_stats_daily_distributed" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "web_stats_daily_distributed")
  database = var.database
  name     = "web_stats_daily_distributed"
  override = try(local.deployment.overrides["web_stats_daily_distributed"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'web_stats_daily', rand())"
  columns = [
    { name = "period_bucket", type = "DateTime" },
    { name = "team_id", type = "UInt64" },
    { name = "host", type = "String" },
    { name = "device_type", type = "String" },
    { name = "pathname", type = "String" },
    { name = "entry_pathname", type = "String" },
    { name = "end_pathname", type = "String" },
    { name = "browser", type = "String" },
    { name = "os", type = "String" },
    { name = "viewport_width", type = "Int64" },
    { name = "viewport_height", type = "Int64" },
    { name = "referring_domain", type = "String" },
    { name = "utm_source", type = "String" },
    { name = "utm_medium", type = "String" },
    { name = "utm_campaign", type = "String" },
    { name = "utm_term", type = "String" },
    { name = "utm_content", type = "String" },
    { name = "country_code", type = "String" },
    { name = "city_name", type = "String" },
    { name = "region_code", type = "String" },
    { name = "region_name", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]
}

module "web_stats_hourly_distributed" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "web_stats_hourly_distributed")
  database = var.database
  name     = "web_stats_hourly_distributed"
  override = try(local.deployment.overrides["web_stats_hourly_distributed"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'web_stats_hourly', rand())"
  columns = [
    { name = "period_bucket", type = "DateTime" },
    { name = "team_id", type = "UInt64" },
    { name = "host", type = "String" },
    { name = "device_type", type = "String" },
    { name = "pathname", type = "String" },
    { name = "entry_pathname", type = "String" },
    { name = "end_pathname", type = "String" },
    { name = "browser", type = "String" },
    { name = "os", type = "String" },
    { name = "viewport_width", type = "Int64" },
    { name = "viewport_height", type = "Int64" },
    { name = "referring_domain", type = "String" },
    { name = "utm_source", type = "String" },
    { name = "utm_medium", type = "String" },
    { name = "utm_campaign", type = "String" },
    { name = "utm_term", type = "String" },
    { name = "utm_content", type = "String" },
    { name = "country_code", type = "String" },
    { name = "city_name", type = "String" },
    { name = "region_code", type = "String" },
    { name = "region_name", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]
}
