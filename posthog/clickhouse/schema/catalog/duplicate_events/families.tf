module "duplicate_events_family" {
  source = "../../lib/table_family"

  name     = "duplicate_events"
  database = var.database
  layout   = "global"
  columns  = local.duplicate_events_columns
  storage = {
    partition_by = "toYYYYMMDD(inserted_at)"
    order_by     = "(team_id, distinct_id, event, inserted_at)"
    ttl          = var.ttl ? "inserted_at + toIntervalDay(7)" : null
    settings     = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_duplicate_events", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  sharding_key = ""
  kafka = {
    topic     = "clickhouse_ingestion_events_duplicates"
    arguments = "settings"
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
    settings = {}
  }
  mv_select = <<-SQL
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
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["duplicate_events", "writable_duplicate_events", "duplicate_events_mv", "kafka_duplicate_events"], name) }
  })
}
