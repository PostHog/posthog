# Tables that hold data, and the materialized views between them.

module "sharded_web_bounces_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_bounces_dimensional_preaggregated")
  database     = var.database
  name         = "sharded_web_bounces_dimensional_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_bounces_dimensional_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_backend, mat_metadata_loggedIn)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "allow_nullable_key = 1, index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_bounces_dimensional_preaggregated_columns
  override     = try(var.overrides["sharded_web_bounces_dimensional_preaggregated"], {})
}

module "sharded_web_goals_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_goals_preaggregated")
  database     = var.database
  name         = "sharded_web_goals_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_goals_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, action_id, time_window_start)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_goals_preaggregated_columns
  override     = try(var.overrides["sharded_web_goals_preaggregated"], {})
}

module "sharded_web_overview_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_overview_preaggregated")
  database     = var.database
  name         = "sharded_web_overview_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_overview_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, time_window_start)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_overview_preaggregated_columns
  override     = try(var.overrides["sharded_web_overview_preaggregated"], {})
}

module "sharded_web_sessions_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_sessions_dimensional_preaggregated")
  database     = var.database
  name         = "sharded_web_sessions_dimensional_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_sessions_dimensional_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, person_id, start_timestamp, session_id_v7)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_sessions_dimensional_preaggregated_columns
  override     = try(var.overrides["sharded_web_sessions_dimensional_preaggregated"], {})
}

module "sharded_web_stats_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_stats_dimensional_preaggregated")
  database     = var.database
  name         = "sharded_web_stats_dimensional_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_stats_dimensional_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_backend, mat_metadata_loggedIn)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "allow_nullable_key = 1, index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_stats_dimensional_preaggregated_columns
  override     = try(var.overrides["sharded_web_stats_dimensional_preaggregated"], {})
}

module "sharded_web_stats_frustration_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_stats_frustration_preaggregated")
  database     = var.database
  name         = "sharded_web_stats_frustration_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_stats_frustration_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, breakdown_value, time_window_start)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_stats_frustration_preaggregated_columns
  override     = try(var.overrides["sharded_web_stats_frustration_preaggregated"], {})
}

module "sharded_web_stats_paths_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_stats_paths_preaggregated")
  database     = var.database
  name         = "sharded_web_stats_paths_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_stats_paths_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, breakdown_value, time_window_start)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_stats_paths_preaggregated_columns
  override     = try(var.overrides["sharded_web_stats_paths_preaggregated"], {})
}

module "sharded_web_stats_paths_preaggregated_pathkey" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_stats_paths_preaggregated_pathkey")
  database     = var.database
  name         = "sharded_web_stats_paths_preaggregated_pathkey"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_stats_paths_preaggregated_pathkey${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, time_window_start, breakdown_value, job_id)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_stats_paths_preaggregated_columns
  override     = try(var.overrides["sharded_web_stats_paths_preaggregated_pathkey"], {})
}

module "sharded_web_stats_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_stats_preaggregated")
  database     = var.database
  name         = "sharded_web_stats_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_stats_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, breakdown_by, time_window_start, breakdown_value)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_stats_preaggregated_columns
  override     = try(var.overrides["sharded_web_stats_preaggregated"], {})
}

module "sharded_web_vitals_paths_preaggregated" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_web_vitals_paths_preaggregated")
  database     = var.database
  name         = "sharded_web_vitals_paths_preaggregated"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.web_vitals_paths_preaggregated${var.zk_path_suffix}', '{replica}', computed_at)"
  partition_by = "toYYYYMMDD(expires_at)"
  order_by     = "(team_id, job_id, time_window_start, path)"
  ttl          = var.ttl ? "toDateTime(expires_at)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.sharded_web_vitals_paths_preaggregated_columns
  override     = try(var.overrides["sharded_web_vitals_paths_preaggregated"], {})
}

module "web_pre_aggregated_bounces" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "web_pre_aggregated_bounces")
  database     = var.database
  name         = "web_pre_aggregated_bounces"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.web_pre_aggregated_bounces${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMMDD(period_bucket)"
  order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  columns      = local.web_pre_aggregated_bounces_columns
  override     = try(var.overrides["web_pre_aggregated_bounces"], {})
}

module "web_pre_aggregated_bounces_staging" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "web_pre_aggregated_bounces_staging")
  database     = var.database
  name         = "web_pre_aggregated_bounces_staging"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.web_pre_aggregated_bounces_staging${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMMDD(period_bucket)"
  order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  columns      = local.web_pre_aggregated_bounces_columns
  override     = try(var.overrides["web_pre_aggregated_bounces_staging"], {})
}

module "web_pre_aggregated_stats" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "web_pre_aggregated_stats")
  database     = var.database
  name         = "web_pre_aggregated_stats"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.web_pre_aggregated_stats${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMMDD(period_bucket)"
  order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  columns      = local.web_pre_aggregated_stats_columns
  override     = try(var.overrides["web_pre_aggregated_stats"], {})
}

module "web_pre_aggregated_stats_staging" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "web_pre_aggregated_stats_staging")
  database     = var.database
  name         = "web_pre_aggregated_stats_staging"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.web_pre_aggregated_stats_staging${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMMDD(period_bucket)"
  order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  columns      = local.web_pre_aggregated_stats_columns
  override     = try(var.overrides["web_pre_aggregated_stats_staging"], {})
}

module "web_pre_aggregated_teams" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "web_pre_aggregated_teams")
  database = var.database
  name     = "web_pre_aggregated_teams"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.web_analytics_team_selection${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(team_id)"
  columns = [
    { name = "team_id", type = "UInt64" },
    { name = "enabled_by", type = "String", default_expression = "'system'" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  override = try(var.overrides["web_pre_aggregated_teams"], {})
}
