module "pg_embeddings_family" {
  source = "../../lib/table_family"

  name     = "pg_embeddings"
  database = var.database
  layout   = "global"
  columns = [
    { name = "domain", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "id", type = "String" },
    { name = "vector", type = "Array(Float32)" },
    { name = "text", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", default_expression = "now('UTC')" },
    { name = "is_deleted", type = "UInt8" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["timestamp", "is_deleted"]
    order_by    = "(team_id, domain, id)"
    settings    = "index_granularity = 512"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["pg_embeddings"], name) }
  })
}
