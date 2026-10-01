module "traces" {
  source     = "./traces"
  database   = var.database
  deployment = try(var.deployment.families.traces, { components = [] })
  ttl        = var.ttl
}
