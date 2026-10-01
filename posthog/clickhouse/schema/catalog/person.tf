module "person" {
  source     = "./person"
  database   = var.database
  deployment = try(var.deployment.families.person, { components = [] })
  depends_on = [module.person_distinct_id]
}
