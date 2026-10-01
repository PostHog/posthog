module "events" {
  source     = "./events"
  database   = var.database
  deployment = try(var.deployment.families.events, { components = [] })
}
