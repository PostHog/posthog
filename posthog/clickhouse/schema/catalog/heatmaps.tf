module "heatmaps" {
  source     = "./heatmaps"
  database   = var.database
  deployment = try(var.deployment.families.heatmaps, { components = [] })
  ttl        = var.ttl
}
