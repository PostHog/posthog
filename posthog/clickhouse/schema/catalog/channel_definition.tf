module "channel_definition" {
  source              = "./channel_definition"
  database            = var.database
  deployment          = try(var.deployment.families.channel_definition, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
