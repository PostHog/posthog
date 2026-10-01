module "query_log_archive_v2_family" {
  source = "../../lib/table_family"

  name     = "query_log_archive_v2"
  database = var.database
  layout   = "global"
  columns  = local.query_log_archive_v2_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.query_log_archive_new"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["query_log_archive_v2"], name) }
  })
}

module "sharded_query_log_archive_family" {
  source = "../../lib/table_family"

  name     = "query_log_archive"
  database = var.database
  layout   = "global"
  columns  = local.sharded_query_log_archive_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
    settings     = "index_granularity = 8192, object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets'"
  }
  routing = {
    read         = true
    read_columns = local.sharded_query_log_archive_columns
  }
  sharding_key = ""
  deployment = merge({
    cluster = "ops"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_query_log_archive", "query_log_archive"], name) }
  })
  names = { storage = "sharded_query_log_archive" }
}

module "sharded_query_log_archive_old_family" {
  source = "../../lib/table_family"

  name     = "query_log_archive_old"
  database = var.database
  columns  = local.query_log_archive_v2_columns
  storage = {
    partition_by = "toYYYYMM(event_date)"
    order_by     = "(team_id, event_date, event_time, query_id)"
  }
  routing = {
    read  = false
    write = false
  }
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.sharded_query_log_archive"
    cluster     = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_query_log_archive_old"], name) }
  })
}
