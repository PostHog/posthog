module "events_json" {
  source     = "./events_json"
  database   = var.database
  deployment = try(var.deployment.families.events_json, { components = [] })
}
