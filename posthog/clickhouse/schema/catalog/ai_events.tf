module "ai_events" {
  source     = "./ai_events"
  database   = var.database
  deployment = try(var.deployment.families.ai_events, { components = [] })
  ttl        = var.ttl
}
