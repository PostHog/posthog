module "error_tracking" {
  source     = "./error_tracking"
  database   = var.database
  deployment = try(var.deployment.families.error_tracking, { components = [] })
}
