module "precalculated" {
  source     = "./precalculated"
  database   = var.database
  deployment = try(var.deployment.families.precalculated, { components = [] })
}
