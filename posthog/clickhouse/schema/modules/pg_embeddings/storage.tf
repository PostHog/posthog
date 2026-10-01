# Tables that hold data, and the materialized views between them.

module "pg_embeddings" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "pg_embeddings")
  database = var.database
  name     = "pg_embeddings"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.pg_embeddings${var.zk_path_suffix}', '{replica}-{shard}', timestamp, is_deleted)"
  order_by = "(team_id, domain, id)"
  settings = "index_granularity = 512"
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
  override = try(var.overrides["pg_embeddings"], {})
}
