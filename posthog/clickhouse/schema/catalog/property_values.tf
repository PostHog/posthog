module "property_values" {
  source     = "./property_values"
  database   = var.database
  deployment = try(var.deployment.families.property_values, { components = [] })
  ttl        = var.ttl
}
