module "web_preaggregated" {
  source              = "./web_preaggregated"
  database            = var.database
  deployment          = try(var.deployment.families.web_preaggregated, { components = [] })
  ttl                 = var.ttl
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
