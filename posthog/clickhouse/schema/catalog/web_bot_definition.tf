module "web_bot_definition" {
  source              = "./web_bot_definition"
  database            = var.database
  deployment          = try(var.deployment.families.web_bot_definition, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
