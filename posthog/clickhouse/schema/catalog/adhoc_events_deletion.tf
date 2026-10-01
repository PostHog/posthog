module "adhoc_events_deletion" {
  source     = "./adhoc_events_deletion"
  database   = var.database
  deployment = try(var.deployment.families.adhoc_events_deletion, { components = [] })
  ttl        = var.ttl
}
