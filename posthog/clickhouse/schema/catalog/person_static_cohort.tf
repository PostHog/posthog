module "person_static_cohort" {
  source     = "./person_static_cohort"
  database   = var.database
  deployment = try(var.deployment.families.person_static_cohort, { components = [] })
}
