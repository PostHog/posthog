# Tables that hold data, and the materialized views between them.

module "clickhouse_cleanup_deleted_persons" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "clickhouse_cleanup_deleted_persons")
  database     = var.database
  name         = "clickhouse_cleanup_deleted_persons"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.clickhouse_cleanup_deleted_persons${var.zk_path_suffix}', '{replica}-{shard}', created_at)"
  partition_by = "run_id"
  order_by     = "(run_id, team_id, person_id)"
  ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "max_version", type = "UInt64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  override = try(var.overrides["clickhouse_cleanup_deleted_persons"], {})
}

module "clickhouse_cleanup_orphaned_distinct_ids" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "clickhouse_cleanup_orphaned_distinct_ids")
  database     = var.database
  name         = "clickhouse_cleanup_orphaned_distinct_ids"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.clickhouse_cleanup_orphaned_distinct_ids${var.zk_path_suffix}', '{replica}-{shard}', created_at)"
  partition_by = "run_id"
  order_by     = "(run_id, team_id, distinct_id)"
  ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "own_tombstone", type = "UInt8" },
    { name = "max_version", type = "Int64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  override = try(var.overrides["clickhouse_cleanup_orphaned_distinct_ids"], {})
}

module "clickhouse_cleanup_revived_distinct_ids" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "clickhouse_cleanup_revived_distinct_ids")
  database     = var.database
  name         = "clickhouse_cleanup_revived_distinct_ids"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_distinct_ids${var.zk_path_suffix}', '{replica}-{shard}', created_at)"
  partition_by = "run_id"
  order_by     = "(run_id, team_id, distinct_id)"
  ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  override = try(var.overrides["clickhouse_cleanup_revived_distinct_ids"], {})
}

module "clickhouse_cleanup_revived_persons" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "clickhouse_cleanup_revived_persons")
  database     = var.database
  name         = "clickhouse_cleanup_revived_persons"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.clickhouse_cleanup_revived_persons${var.zk_path_suffix}', '{replica}-{shard}', created_at)"
  partition_by = "run_id"
  order_by     = "(run_id, team_id, person_id)"
  ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  override = try(var.overrides["clickhouse_cleanup_revived_persons"], {})
}
