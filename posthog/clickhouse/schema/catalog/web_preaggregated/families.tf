module "sharded_web_bounces_dimensional_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_bounces_dimensional_preaggregated", "web_bounces_dimensional_preaggregated"], name) }
  })
}

module "sharded_web_goals_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_goals_preaggregated", "web_goals_preaggregated"], name) }
  })
}

module "sharded_web_overview_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_overview_preaggregated", "web_overview_preaggregated"], name) }
  })
}

module "sharded_web_sessions_dimensional_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_sessions_dimensional_preaggregated", "web_sessions_dimensional_preaggregated"], name) }
  })
}

module "sharded_web_stats_dimensional_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_stats_dimensional_preaggregated", "web_stats_dimensional_preaggregated"], name) }
  })
}

module "sharded_web_stats_frustration_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_stats_frustration_preaggregated", "web_stats_frustration_preaggregated"], name) }
  })
}

module "sharded_web_stats_paths_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_stats_paths_preaggregated", "web_stats_paths_preaggregated"], name) }
  })
}

module "sharded_web_stats_paths_preaggregated_pathkey_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_stats_paths_preaggregated_pathkey", "web_stats_paths_preaggregated_pathkey"], name) }
  })
}

module "sharded_web_stats_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_stats_preaggregated", "web_stats_preaggregated"], name) }
  })
}

module "sharded_web_vitals_paths_preaggregated_family" {
  source = "../../lib/table_family"

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
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_web_vitals_paths_preaggregated", "web_vitals_paths_preaggregated"], name) }
  })
}

module "web_pre_aggregated_bounces_family" {
  source = "../../lib/table_family"

  name     = "web_pre_aggregated_bounces"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_bounces_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["web_pre_aggregated_bounces"], name) }
  })
}

module "web_pre_aggregated_bounces_staging_family" {
  source = "../../lib/table_family"

  name     = "web_pre_aggregated_bounces_staging"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_bounces_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["web_pre_aggregated_bounces_staging"], name) }
  })
}

module "web_pre_aggregated_stats_family" {
  source = "../../lib/table_family"

  name     = "web_pre_aggregated_stats"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_stats_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["web_pre_aggregated_stats"], name) }
  })
}

module "web_pre_aggregated_stats_staging_family" {
  source = "../../lib/table_family"

  name     = "web_pre_aggregated_stats_staging"
  database = var.database
  layout   = "global"
  columns  = local.web_pre_aggregated_stats_columns
  storage = {
    partition_by = "toYYYYMMDD(period_bucket)"
    order_by     = "(team_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, has_fbclid, mat_metadata_loggedIn, mat_metadata_backend)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["web_pre_aggregated_stats_staging"], name) }
  })
}

module "web_pre_aggregated_teams_family" {
  source = "../../lib/table_family"

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
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["web_pre_aggregated_teams"], name) }
  })
}
