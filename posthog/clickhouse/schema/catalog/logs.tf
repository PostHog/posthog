module "logs" {
  source     = "./logs"
  database   = var.database
  deployment = try(var.deployment.families.logs, { components = [] })
  ttl        = var.ttl
}
