module "llma_metrics_daily" {
  source     = "./llma_metrics_daily"
  database   = var.database
  deployment = try(var.deployment.families.llma_metrics_daily, { components = [] })
}
