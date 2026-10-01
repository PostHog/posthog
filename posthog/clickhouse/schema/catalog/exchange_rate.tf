module "exchange_rate" {
  source              = "./exchange_rate"
  database            = var.database
  deployment          = try(var.deployment.families.exchange_rate, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
