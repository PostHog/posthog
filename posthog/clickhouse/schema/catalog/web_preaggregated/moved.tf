moved {
  from = module.sharded_web_bounces_dimensional_preaggregated
  to   = module.sharded_web_bounces_dimensional_preaggregated_family.module.storage
}

moved {
  from = module.web_bounces_dimensional_preaggregated
  to   = module.sharded_web_bounces_dimensional_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_goals_preaggregated
  to   = module.sharded_web_goals_preaggregated_family.module.storage
}

moved {
  from = module.web_goals_preaggregated
  to   = module.sharded_web_goals_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_overview_preaggregated
  to   = module.sharded_web_overview_preaggregated_family.module.storage
}

moved {
  from = module.web_overview_preaggregated
  to   = module.sharded_web_overview_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_sessions_dimensional_preaggregated
  to   = module.sharded_web_sessions_dimensional_preaggregated_family.module.storage
}

moved {
  from = module.web_sessions_dimensional_preaggregated
  to   = module.sharded_web_sessions_dimensional_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_stats_dimensional_preaggregated
  to   = module.sharded_web_stats_dimensional_preaggregated_family.module.storage
}

moved {
  from = module.web_stats_dimensional_preaggregated
  to   = module.sharded_web_stats_dimensional_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_stats_frustration_preaggregated
  to   = module.sharded_web_stats_frustration_preaggregated_family.module.storage
}

moved {
  from = module.web_stats_frustration_preaggregated
  to   = module.sharded_web_stats_frustration_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_stats_paths_preaggregated
  to   = module.sharded_web_stats_paths_preaggregated_family.module.storage
}

moved {
  from = module.web_stats_paths_preaggregated
  to   = module.sharded_web_stats_paths_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_stats_paths_preaggregated_pathkey
  to   = module.sharded_web_stats_paths_preaggregated_pathkey_family.module.storage
}

moved {
  from = module.web_stats_paths_preaggregated_pathkey
  to   = module.sharded_web_stats_paths_preaggregated_pathkey_family.module.read
}

moved {
  from = module.sharded_web_stats_preaggregated
  to   = module.sharded_web_stats_preaggregated_family.module.storage
}

moved {
  from = module.web_stats_preaggregated
  to   = module.sharded_web_stats_preaggregated_family.module.read
}

moved {
  from = module.sharded_web_vitals_paths_preaggregated
  to   = module.sharded_web_vitals_paths_preaggregated_family.module.storage
}

moved {
  from = module.web_vitals_paths_preaggregated
  to   = module.sharded_web_vitals_paths_preaggregated_family.module.read
}

moved {
  from = module.web_pre_aggregated_bounces
  to   = module.web_pre_aggregated_bounces_family.module.storage
}

moved {
  from = module.web_pre_aggregated_bounces_staging
  to   = module.web_pre_aggregated_bounces_staging_family.module.storage
}

moved {
  from = module.web_pre_aggregated_stats
  to   = module.web_pre_aggregated_stats_family.module.storage
}

moved {
  from = module.web_pre_aggregated_stats_staging
  to   = module.web_pre_aggregated_stats_staging_family.module.storage
}

moved {
  from = module.web_pre_aggregated_teams
  to   = module.web_pre_aggregated_teams_family.module.storage
}
