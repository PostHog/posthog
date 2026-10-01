module "plugin_log_entries_family" {
  source = "../../lib/table_family"

  name     = "plugin_log_entries"
  database = var.database
  layout   = "global"
  columns  = local.plugin_log_entries_columns
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, plugin_id, plugin_config_id, timestamp)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalWeek(1)" : null
    settings     = "index_granularity = 512"
  }
  sharding_key = ""
  kafka = {
    topic          = "plugin_log_entries"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_plugin_log_entries_columns
    settings       = {}
  }
  mv_select = <<-SQL
id,
    team_id,
    plugin_id,
    plugin_config_id,
    timestamp,
    source,
    type,
    message,
    instance_id,
    _timestamp,
    _offset
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["plugin_log_entries", "writable_plugin_log_entries", "plugin_log_entries_mv", "kafka_plugin_log_entries"], name) }
  })
}
