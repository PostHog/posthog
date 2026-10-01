module "usage_report_events_preagg" {
  source     = "./usage_report_events_preagg"
  database   = var.database
  deployment = try(var.deployment.families.usage_report_events_preagg, { components = [] })
  ttl        = var.ttl
}
