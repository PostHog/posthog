module "experiments_preaggregated" {
  source     = "./experiments_preaggregated"
  database   = var.database
  deployment = try(var.deployment.families.experiments_preaggregated, { components = [] })
  ttl        = var.ttl
}
