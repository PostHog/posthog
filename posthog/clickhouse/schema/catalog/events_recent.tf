module "events_recent" {
  source     = "./events_recent"
  database   = var.database
  deployment = try(var.deployment.families.events_recent, { components = [] })
  ttl        = var.ttl
  depends_on = [module.events]
}
