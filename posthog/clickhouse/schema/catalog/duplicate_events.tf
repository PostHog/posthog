module "duplicate_events" {
  source     = "./duplicate_events"
  database   = var.database
  deployment = try(var.deployment.families.duplicate_events, { components = [] })
  ttl        = var.ttl
}
