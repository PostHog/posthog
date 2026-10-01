# Kafka tables and the materialized views that consume them.

module "kafka_log_entries_aux" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_log_entries_aux")
  database = var.database
  name     = "kafka_log_entries_aux"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries_aux', kafka_max_block_size = 100000, kafka_num_consumers = 1, kafka_poll_timeout_ms = 10000, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_aux"], {})
}

module "kafka_log_entries_v3" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_log_entries_v3")
  database = var.database
  name     = "kafka_log_entries_v3"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries', kafka_skip_broken_messages = 100, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_v3"], {})
}

module "kafka_log_entries_ws" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(local.deployment.exclude, "kafka_log_entries_ws")
  database = var.database
  name     = "kafka_log_entries_ws"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_log_entries_ws', kafka_skip_broken_messages = 100, kafka_topic_list = 'log_entries'"
  columns  = local.kafka_log_entries_v3_columns
  override = try(local.deployment.overrides["kafka_log_entries_ws"], {})
}

module "log_entries_aux_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "log_entries_aux_mv")
  database = var.database
  name     = "log_entries_aux_mv"
  to_table = "${var.database}.writable_log_entries_aux"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_aux
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_aux_mv"], {})

  depends_on = [
    module.kafka_log_entries_aux,
    module.log_entries_data_family,
  ]
}

module "log_entries_v3_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "log_entries_v3_mv")
  database = var.database
  name     = "log_entries_v3_mv"
  to_table = "${var.database}.writable_log_entries"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_v3
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_v3_mv"], {})

  depends_on = [
    module.kafka_log_entries_v3,
    module.sharded_log_entries_family,
  ]
}

module "log_entries_ws_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(local.deployment.exclude, "log_entries_ws_mv")
  database = var.database
  name     = "log_entries_ws_mv"
  to_table = "${var.database}.writable_log_entries"
  query    = <<-SQL
    SELECT
        team_id,
        log_source,
        log_source_id,
        instance_id,
        timestamp,
        level,
        message,
        _timestamp,
        _offset
    FROM ${var.database}.kafka_log_entries_ws
    WHERE toDate(timestamp) <= today()
  SQL
  override = try(local.deployment.overrides["log_entries_ws_mv"], {})

  depends_on = [
    module.kafka_log_entries_ws,
    module.sharded_log_entries_family,
  ]
}
