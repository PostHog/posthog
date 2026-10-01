# Kafka tables and the materialized views that consume them.

module "kafka_usage_report_events_preagg" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_usage_report_events_preagg")
  database = var.database
  name     = "kafka_usage_report_events_preagg"
  engine   = "Kafka(warpstream_ingestion)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_usage_report_events_preagg', kafka_num_consumers = 1, kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_topic_list = 'clickhouse_events_json'"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
  ]
  override = try(var.overrides["kafka_usage_report_events_preagg"], {})
}

module "usage_report_events_preagg_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "usage_report_events_preagg_mv")
  database = var.database
  name     = "usage_report_events_preagg_mv"
  to_table = "${var.database}.writable_usage_report_events_preagg"
  query    = <<-SQL
    SELECT
        toDate(timestamp) AS date,
        team_id,
        person_mode,
        JSONExtractString(properties, '$lib') AS lib,
        event,
        uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
        sumState(toUInt64(1)) AS event_count
    FROM ${var.database}.kafka_usage_report_events_preagg
    GROUP BY
        date,
        team_id,
        person_mode,
        lib,
        event
  SQL
  override = try(var.overrides["usage_report_events_preagg_mv"], {})

  depends_on = [
    module.kafka_usage_report_events_preagg,
    module.writable_usage_report_events_preagg,
  ]
}
