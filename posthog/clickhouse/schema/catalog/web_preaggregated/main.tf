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

variable "dictionary_user" {
  description = "User the dictionaries connect to their source as."
  type        = string
  default     = "default"
}

variable "dictionary_password" {
  description = "Password of `dictionary_user`."
  type        = string
  default     = ""
  sensitive   = true
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

locals {

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

# Column lists that more than one object uses.

locals {
  sharded_web_goals_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "action_id", type = "Int64" },
    { name = "count_state", type = "AggregateFunction(sum, Int64)" },
    { name = "unique_persons_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_stats_frustration_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "breakdown_value", type = "String" },
    { name = "sum_rage_clicks_state", type = "AggregateFunction(sum, Int64)" },
    { name = "sum_dead_clicks_state", type = "AggregateFunction(sum, Int64)" },
    { name = "sum_errors_state", type = "AggregateFunction(sum, Int64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_stats_paths_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "breakdown_value", type = "String" },
    { name = "uniq_users_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sum_pageviews_state", type = "AggregateFunction(sum, Int64)" },
    { name = "avg_bounce_state", type = "AggregateFunction(avg, Nullable(Float64))" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_stats_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "breakdown_by", type = "String" },
    { name = "breakdown_value", type = "String" },
    { name = "uniq_users_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sum_pageviews_state", type = "AggregateFunction(sum, Int64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_overview_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "uniq_users_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "uniq_sessions_state", type = "AggregateFunction(uniq, String)" },
    { name = "sum_pageviews_state", type = "AggregateFunction(sum, Int64)" },
    { name = "avg_duration_state", type = "AggregateFunction(avg, Float64)" },
    { name = "avg_bounce_state", type = "AggregateFunction(avg, Int64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_vitals_paths_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "time_window_start", type = "DateTime64(6, 'UTC')" },
    { name = "path", type = "String" },
    { name = "inp_quantiles_state", type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)" },
    { name = "lcp_quantiles_state", type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)" },
    { name = "cls_quantiles_state", type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)" },
    { name = "fcp_quantiles_state", type = "AggregateFunction(quantiles(0.75, 0.9, 0.99), Float64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_sessions_dimensional_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "period_bucket", type = "DateTime" },
    { name = "session_id_v7", type = "UInt128" },
    { name = "person_id", type = "UUID" },
    { name = "start_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "min_event_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "max_event_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "channel_type", type = "String" },
    { name = "utm_source", type = "String" },
    { name = "utm_medium", type = "String" },
    { name = "utm_campaign", type = "String" },
    { name = "utm_term", type = "String" },
    { name = "utm_content", type = "String" },
    { name = "referring_domain", type = "String" },
    { name = "entry_pathname", type = "String" },
    { name = "pageview_count", type = "UInt64" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  web_pre_aggregated_stats_columns = [
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
    { name = "has_gclid", type = "Bool" },
    { name = "has_gad_source_paid_search", type = "Bool" },
    { name = "has_fbclid", type = "Bool" },
    { name = "mat_metadata_loggedIn", type = "Bool" },
    { name = "mat_metadata_backend", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]

  web_pre_aggregated_bounces_columns = [
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
    { name = "has_gclid", type = "Bool" },
    { name = "has_gad_source_paid_search", type = "Bool" },
    { name = "has_fbclid", type = "Bool" },
    { name = "mat_metadata_loggedIn", type = "Bool" },
    { name = "mat_metadata_backend", type = "String" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "bounces_count_state", type = "AggregateFunction(sum, UInt64)" },
    { name = "total_session_duration_state", type = "AggregateFunction(sum, Int64)" },
    { name = "total_session_count_state", type = "AggregateFunction(sum, UInt64)" },
  ]

  sharded_web_stats_dimensional_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "period_bucket", type = "DateTime" },
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
    { name = "has_gclid", type = "Bool" },
    { name = "has_gad_source_paid_search", type = "Bool" },
    { name = "has_fbclid", type = "Bool" },
    { name = "mat_metadata_backend", type = "Nullable(String)" },
    { name = "mat_metadata_loggedIn", type = "Nullable(Bool)" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, Int64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]

  sharded_web_bounces_dimensional_preaggregated_columns = [
    { name = "team_id", type = "Int64" },
    { name = "job_id", type = "UUID" },
    { name = "period_bucket", type = "DateTime" },
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
    { name = "has_gclid", type = "Bool" },
    { name = "has_gad_source_paid_search", type = "Bool" },
    { name = "has_fbclid", type = "Bool" },
    { name = "mat_metadata_backend", type = "Nullable(String)" },
    { name = "mat_metadata_loggedIn", type = "Nullable(Bool)" },
    { name = "persons_uniq_state", type = "AggregateFunction(uniq, UUID)" },
    { name = "sessions_uniq_state", type = "AggregateFunction(uniq, String)" },
    { name = "pageviews_count_state", type = "AggregateFunction(sum, Int64)" },
    { name = "bounces_count_state", type = "AggregateFunction(sum, Int64)" },
    { name = "total_session_duration_state", type = "AggregateFunction(sum, Int64)" },
    { name = "total_session_count_state", type = "AggregateFunction(sum, Int64)" },
    { name = "computed_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "expires_at", type = "DateTime64(6, 'UTC')", default_expression = "now() + toIntervalDay(7)" },
  ]
}

module "sharded_web_bounces_dimensional_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_bounces_dimensional_preaggregated"
  database = var.database
  columns  = local.sharded_web_bounces_dimensional_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_backend, mat_metadata_loggedIn)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "allow_nullable_key = 1, index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_bounces_dimensional_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_goals_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_goals_preaggregated"
  database = var.database
  columns  = local.sharded_web_goals_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, action_id, time_window_start)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_goals_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_overview_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_overview_preaggregated"
  database = var.database
  columns  = local.sharded_web_overview_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, time_window_start)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_overview_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_sessions_dimensional_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_sessions_dimensional_preaggregated"
  database = var.database
  columns  = local.sharded_web_sessions_dimensional_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, person_id, start_timestamp, session_id_v7)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "cityHash64(person_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_sessions_dimensional_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_stats_dimensional_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_stats_dimensional_preaggregated"
  database = var.database
  columns  = local.sharded_web_stats_dimensional_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_backend, mat_metadata_loggedIn)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "allow_nullable_key = 1, index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_stats_dimensional_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_stats_frustration_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_stats_frustration_preaggregated"
  database = var.database
  columns  = local.sharded_web_stats_frustration_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, breakdown_value, time_window_start)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_stats_frustration_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_stats_paths_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_stats_paths_preaggregated"
  database = var.database
  columns  = local.sharded_web_stats_paths_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, breakdown_value, time_window_start)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_stats_paths_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_stats_paths_preaggregated_pathkey_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_stats_paths_preaggregated_pathkey"
  database = var.database
  columns  = local.sharded_web_stats_paths_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, time_window_start, breakdown_value, job_id)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(breakdown_value)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_stats_paths_preaggregated_pathkey"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_stats_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_stats_preaggregated"
  database = var.database
  columns  = local.sharded_web_stats_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, breakdown_by, time_window_start, breakdown_value)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_stats_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "sharded_web_vitals_paths_preaggregated_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_vitals_paths_preaggregated"
  database = var.database
  columns  = local.sharded_web_vitals_paths_preaggregated_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["computed_at"]
    partition_by = "toYYYYMMDD(expires_at)"
    order_by     = "(team_id, job_id, time_window_start, path)"
    ttl          = var.ttl ? "toDateTime(expires_at)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  routing = {
    write = false
  }
  sharding_key = "sipHash64(job_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.web_vitals_paths_preaggregated"
    cluster     = "aux"
  }, local.deployment)
}

module "web_pre_aggregated_bounces_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_pre_aggregated_bounces"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_bounces_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = local.deployment
}

module "web_pre_aggregated_bounces_staging_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_pre_aggregated_bounces_staging"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_bounces_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = local.deployment
}

module "web_pre_aggregated_stats_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_pre_aggregated_stats"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_stats_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = local.deployment
}

module "web_pre_aggregated_stats_staging_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_pre_aggregated_stats_staging"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_stats_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = local.deployment
}

module "web_pre_aggregated_teams_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "web_pre_aggregated_teams"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "enabled_by", type = "String", default_expression = "'system'" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id)"
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.web_analytics_team_selection"
  }, local.deployment)
}

# Distributed tables, views and dictionaries that queries read from.




module "web_pre_aggregated_teams_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "web_pre_aggregated_teams_dict")
  database    = var.database
  name        = "web_pre_aggregated_teams_dict"
  primary_key = ["team_id"]
  attributes = [
    { name = "team_id", type = "UInt64" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT     team_id FROM     `${var.database}`.`web_pre_aggregated_teams` FINAL WHERE version > 0')"
  layout        = "HASHED()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(local.deployment.overrides["web_pre_aggregated_teams_dict"], {})

  depends_on = [
    module.web_pre_aggregated_teams_family,
  ]
}
