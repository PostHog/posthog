module "log_entries_data_family" {
  source = "../../lib/table_family"

  name     = "log_entries_distributed"
  database = var.database
  columns  = local.log_entries_data_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  }
  sharding_key = ""
  deployment = merge({
    keeper_path = "/clickhouse/tables/noshard/${var.database}.log_entries_data"
    cluster     = "aux"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["log_entries_data", "log_entries_distributed", "writable_log_entries_aux"], name) }
  })
  names = { storage = "log_entries_data", write = "writable_log_entries_aux" }
}

module "sharded_log_entries_family" {
  source = "../../lib/table_family"

  name     = "log_entries"
  database = var.database
  columns  = local.log_entries_data_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, log_source, log_source_id, instance_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
    settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  }
  sharding_key = "rand()"
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_log_entries", "log_entries", "writable_log_entries"], name) }
  })
}
