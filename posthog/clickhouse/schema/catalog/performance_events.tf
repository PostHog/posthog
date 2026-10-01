module "performance_events" {
  source     = "./performance_events"
  database   = var.database
  deployment = try(var.deployment.families.performance_events, { components = [] })
  ttl        = var.ttl
}
