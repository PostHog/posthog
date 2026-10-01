module "custom_metrics" {
  source     = "./custom_metrics"
  database   = var.database
  deployment = try(var.deployment.families.custom_metrics, { components = [] })
}
