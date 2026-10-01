# Distributed tables, views and dictionaries that queries read from.

module "web_bounces_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_bounces_dimensional_preaggregated")
  database = var.database
  name     = "web_bounces_dimensional_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_bounces_dimensional_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_bounces_dimensional_preaggregated_columns
  override = try(var.overrides["web_bounces_dimensional_preaggregated"], {})
}

module "web_goals_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_goals_preaggregated")
  database = var.database
  name     = "web_goals_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_goals_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_goals_preaggregated_columns
  override = try(var.overrides["web_goals_preaggregated"], {})
}

module "web_overview_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_overview_preaggregated")
  database = var.database
  name     = "web_overview_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_overview_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_overview_preaggregated_columns
  override = try(var.overrides["web_overview_preaggregated"], {})
}

module "web_pre_aggregated_teams_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(var.exclude, "web_pre_aggregated_teams_dict")
  database    = var.database
  name        = "web_pre_aggregated_teams_dict"
  primary_key = ["team_id"]
  attributes = [
    { name = "team_id", type = "UInt64" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT     team_id FROM     `${var.database}`.`web_pre_aggregated_teams` FINAL WHERE version > 0')"
  layout        = "HASHED()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(var.overrides["web_pre_aggregated_teams_dict"], {})

  depends_on = [
    module.web_pre_aggregated_teams,
  ]
}

module "web_sessions_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_sessions_dimensional_preaggregated")
  database = var.database
  name     = "web_sessions_dimensional_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_sessions_dimensional_preaggregated', cityHash64(person_id))"
  columns  = local.sharded_web_sessions_dimensional_preaggregated_columns
  override = try(var.overrides["web_sessions_dimensional_preaggregated"], {})
}

module "web_stats_dimensional_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_stats_dimensional_preaggregated")
  database = var.database
  name     = "web_stats_dimensional_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_stats_dimensional_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_stats_dimensional_preaggregated_columns
  override = try(var.overrides["web_stats_dimensional_preaggregated"], {})
}

module "web_stats_frustration_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_stats_frustration_preaggregated")
  database = var.database
  name     = "web_stats_frustration_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_stats_frustration_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_stats_frustration_preaggregated_columns
  override = try(var.overrides["web_stats_frustration_preaggregated"], {})
}

module "web_stats_paths_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_stats_paths_preaggregated")
  database = var.database
  name     = "web_stats_paths_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_stats_paths_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_stats_paths_preaggregated_columns
  override = try(var.overrides["web_stats_paths_preaggregated"], {})
}

module "web_stats_paths_preaggregated_pathkey" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_stats_paths_preaggregated_pathkey")
  database = var.database
  name     = "web_stats_paths_preaggregated_pathkey"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_stats_paths_preaggregated_pathkey', sipHash64(breakdown_value))"
  columns  = local.sharded_web_stats_paths_preaggregated_columns
  override = try(var.overrides["web_stats_paths_preaggregated_pathkey"], {})
}

module "web_stats_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_stats_preaggregated")
  database = var.database
  name     = "web_stats_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_stats_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_stats_preaggregated_columns
  override = try(var.overrides["web_stats_preaggregated"], {})
}

module "web_vitals_paths_preaggregated" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "web_vitals_paths_preaggregated")
  database = var.database
  name     = "web_vitals_paths_preaggregated"
  engine   = "Distributed('aux', '${var.database}', 'sharded_web_vitals_paths_preaggregated', sipHash64(job_id))"
  columns  = local.sharded_web_vitals_paths_preaggregated_columns
  override = try(var.overrides["web_vitals_paths_preaggregated"], {})
}
