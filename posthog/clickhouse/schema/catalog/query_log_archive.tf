module "query_log_archive" {
  source     = "./query_log_archive"
  database   = var.database
  deployment = try(var.deployment.families.query_log_archive, { components = [] })
}
