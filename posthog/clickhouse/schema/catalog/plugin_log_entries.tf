module "plugin_log_entries" {
  source     = "./plugin_log_entries"
  database   = var.database
  deployment = try(var.deployment.families.plugin_log_entries, { components = [] })
  ttl        = var.ttl
}
