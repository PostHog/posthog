# Kafka tables and the materialized views that consume them.

module "kafka_plugin_log_entries" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_plugin_log_entries")
  database = var.database
  name     = "kafka_plugin_log_entries"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_topic_list = 'plugin_log_entries'"
  columns  = local.kafka_plugin_log_entries_columns
  override = try(var.overrides["kafka_plugin_log_entries"], {})
}

module "plugin_log_entries_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "plugin_log_entries_mv")
  database = var.database
  name     = "plugin_log_entries_mv"
  to_table = "${var.database}.writable_plugin_log_entries"
  query    = <<-SQL
    SELECT
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
    FROM ${var.database}.kafka_plugin_log_entries
  SQL
  override = try(var.overrides["plugin_log_entries_mv"], {})

  depends_on = [
    module.kafka_plugin_log_entries,
    module.writable_plugin_log_entries,
  ]
}
