module "events_team_daily_stats" {
  source     = "./events_team_daily_stats"
  database   = var.database
  deployment = try(var.deployment.families.events_team_daily_stats, { components = [] })
}
