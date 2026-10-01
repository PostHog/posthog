module "log_entries" {
  source     = "./log_entries"
  database   = var.database
  deployment = try(var.deployment.families.log_entries, { components = [] })
  ttl        = var.ttl
}
