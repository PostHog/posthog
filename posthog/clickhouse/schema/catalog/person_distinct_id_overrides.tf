module "person_distinct_id_overrides" {
  source              = "./person_distinct_id_overrides"
  database            = var.database
  deployment          = try(var.deployment.families.person_distinct_id_overrides, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
