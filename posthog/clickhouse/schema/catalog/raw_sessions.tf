module "raw_sessions" {
  source     = "./raw_sessions"
  database   = var.database
  deployment = try(var.deployment.families.raw_sessions, { components = [] })
  depends_on = [module.events, module.session_replay]
}
