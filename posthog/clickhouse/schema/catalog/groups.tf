module "groups" {
  source     = "./groups"
  database   = var.database
  deployment = try(var.deployment.families.groups, { components = [] })
}
