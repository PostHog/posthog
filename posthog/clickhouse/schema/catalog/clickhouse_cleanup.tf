module "clickhouse_cleanup" {
  source     = "./clickhouse_cleanup"
  database   = var.database
  deployment = try(var.deployment.families.clickhouse_cleanup, { components = [] })
  ttl        = var.ttl
}
