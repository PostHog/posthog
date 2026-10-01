module "clickhouse_cleanup_deleted_persons_family" {
  source = "../../lib/table_family"

  name     = "clickhouse_cleanup_deleted_persons"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "max_version", type = "UInt64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, person_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["clickhouse_cleanup_deleted_persons"], name) }
  })
}

module "clickhouse_cleanup_orphaned_distinct_ids_family" {
  source = "../../lib/table_family"

  name     = "clickhouse_cleanup_orphaned_distinct_ids"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "own_tombstone", type = "UInt8" },
    { name = "max_version", type = "Int64" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, distinct_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["clickhouse_cleanup_orphaned_distinct_ids"], name) }
  })
}

module "clickhouse_cleanup_revived_distinct_ids_family" {
  source = "../../lib/table_family"

  name     = "clickhouse_cleanup_revived_distinct_ids"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, distinct_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["clickhouse_cleanup_revived_distinct_ids"], name) }
  })
}

module "clickhouse_cleanup_revived_persons_family" {
  source = "../../lib/table_family"

  name     = "clickhouse_cleanup_revived_persons"
  database = var.database
  layout   = "global"
  columns = [
    { name = "run_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["created_at"]
    partition_by = "run_id"
    order_by     = "(run_id, team_id, person_id)"
    ttl          = var.ttl ? "created_at + toIntervalDay(14)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["clickhouse_cleanup_revived_persons"], name) }
  })
}
