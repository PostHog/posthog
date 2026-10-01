module "metrics" {
  source     = "./metrics"
  database   = var.database
  deployment = try(var.deployment.families.metrics, { components = [] })
  ttl        = var.ttl
}
