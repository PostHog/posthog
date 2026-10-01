module "sessions" {
  source     = "./sessions"
  database   = var.database
  deployment = try(var.deployment.families.sessions, { components = [] })
  depends_on = [module.events]
}
