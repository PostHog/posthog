module "platform_alert_events" {
  source     = "./platform_alert_events"
  database   = var.database
  deployment = try(var.deployment.families.platform_alert_events, { components = [] })
  ttl        = var.ttl
}
