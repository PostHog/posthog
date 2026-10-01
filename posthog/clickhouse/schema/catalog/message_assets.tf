module "message_assets" {
  source     = "./message_assets"
  database   = var.database
  deployment = try(var.deployment.families.message_assets, { components = [] })
  ttl        = var.ttl
}
