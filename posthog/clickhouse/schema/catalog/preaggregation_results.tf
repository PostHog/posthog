module "preaggregation_results" {
  source     = "./preaggregation_results"
  database   = var.database
  deployment = try(var.deployment.families.preaggregation_results, { components = [] })
  ttl        = var.ttl
}
