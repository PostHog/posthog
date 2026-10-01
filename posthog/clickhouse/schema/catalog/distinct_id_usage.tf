module "distinct_id_usage" {
  source     = "./distinct_id_usage"
  database   = var.database
  deployment = try(var.deployment.families.distinct_id_usage, { components = [] })
  ttl        = var.ttl
}
