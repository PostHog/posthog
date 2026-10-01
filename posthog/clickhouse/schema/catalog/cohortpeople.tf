module "cohortpeople" {
  source     = "./cohortpeople"
  database   = var.database
  deployment = try(var.deployment.families.cohortpeople, { components = [] })
}
