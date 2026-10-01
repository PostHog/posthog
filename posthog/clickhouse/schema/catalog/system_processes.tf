module "system_processes" {
  source     = "./system_processes"
  database   = var.database
  deployment = try(var.deployment.families.system_processes, { components = [] })
}
