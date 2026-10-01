module "person_distinct_id" {
  source     = "./person_distinct_id"
  database   = var.database
  deployment = try(var.deployment.families.person_distinct_id, { components = [] })
}
