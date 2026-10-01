module "person_overrides" {
  source              = "./person_overrides"
  database            = var.database
  deployment          = try(var.deployment.families.person_overrides, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
