module "ingestion_warnings" {
  source     = "./ingestion_warnings"
  database   = var.database
  deployment = try(var.deployment.families.ingestion_warnings, { components = [] })
  ttl        = var.ttl
}
