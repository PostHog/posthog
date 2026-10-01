module "marketing_preaggregated" {
  source     = "./marketing_preaggregated"
  database   = var.database
  deployment = try(var.deployment.families.marketing_preaggregated, { components = [] })
  ttl        = var.ttl
}
