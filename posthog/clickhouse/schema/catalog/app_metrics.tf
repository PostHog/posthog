module "app_metrics" {
  source     = "./app_metrics"
  database   = var.database
  deployment = try(var.deployment.families.app_metrics, { components = [] })
  ttl        = var.ttl
}
