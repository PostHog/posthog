module "hog_invocation_results" {
  source     = "./hog_invocation_results"
  database   = var.database
  deployment = try(var.deployment.families.hog_invocation_results, { components = [] })
  ttl        = var.ttl
}
