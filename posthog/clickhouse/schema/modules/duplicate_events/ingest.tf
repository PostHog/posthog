# Kafka tables and the materialized views that consume them.

module "duplicate_events_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "duplicate_events_mv")
  database = var.database
  name     = "duplicate_events_mv"
  to_table = "${var.database}.writable_duplicate_events"
  query    = <<-SQL
    SELECT
        team_id,
        distinct_id,
        event,
        source_uuid,
        duplicate_uuid,
        similarity_score,
        dedup_type,
        is_confirmed,
        reason,
        version,
        different_property_count,
        properties_similarity,
        source_message,
        duplicate_message,
        JSONExtract(distinct_fields, 'Array(Tuple(field_name String, original_value String, new_value String))') AS distinct_fields,
        inserted_at,
        _timestamp,
        _offset,
        _partition
    FROM ${var.database}.kafka_duplicate_events
  SQL
  override = try(var.overrides["duplicate_events_mv"], {})

  depends_on = [
    module.kafka_duplicate_events,
    module.writable_duplicate_events,
  ]
}

module "kafka_duplicate_events" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_duplicate_events")
  database = var.database
  name     = "kafka_duplicate_events"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_duplicate_events', kafka_topic_list = 'clickhouse_ingestion_events_duplicates'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "event", type = "String" },
    { name = "source_uuid", type = "UUID" },
    { name = "duplicate_uuid", type = "UUID" },
    { name = "similarity_score", type = "Float64" },
    { name = "dedup_type", type = "LowCardinality(String)" },
    { name = "is_confirmed", type = "UInt8" },
    { name = "reason", type = "Nullable(String)" },
    { name = "version", type = "String" },
    { name = "different_property_count", type = "UInt32" },
    { name = "properties_similarity", type = "Float64" },
    { name = "source_message", type = "String" },
    { name = "duplicate_message", type = "String" },
    { name = "distinct_fields", type = "String" },
    { name = "inserted_at", type = "DateTime64(3, 'UTC')" },
  ]
  override = try(var.overrides["kafka_duplicate_events"], {})
}
