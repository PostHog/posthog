module "flag_evaluations" {
  source     = "./flag_evaluations"
  database   = var.database
  deployment = try(var.deployment.families.flag_evaluations, { components = [] })
  ttl        = var.ttl
}
