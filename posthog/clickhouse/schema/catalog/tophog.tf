module "tophog" {
  source     = "./tophog"
  database   = var.database
  deployment = try(var.deployment.families.tophog, { components = [] })
  ttl        = var.ttl
}
