module "cohort_membership" {
  source     = "./cohort_membership"
  database   = var.database
  deployment = try(var.deployment.families.cohort_membership, { components = [] })
}
