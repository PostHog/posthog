# Kafka tables and the materialized views that consume them.

module "events_json_table_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "events_json_table_mv")
  database = var.database
  name     = "events_json_table_mv"
  to_table = "${var.database}.writable_events_json"
  query    = <<-SQL
    SELECT
        *,
        accurateCast(byteSize(*) + byteSize(toUInt32(0)), 'UInt32') AS total_event_size
    FROM
    (
        SELECT
            uuid,
            event,
            cleaned.properties AS properties,
            cleaned.temporary_properties AS temporary_properties,
            cleaned.properties_null_keys AS properties_null_keys,
            cleaned.temporary_properties_null_keys AS temporary_properties_null_keys,
            now64() AS inserted_at,
            timestamp,
            team_id,
            distinct_id,
            elements_chain,
            created_at,
            person_id,
            cleaned.person_properties AS person_properties,
            cleaned.person_properties_null_keys AS person_properties_null_keys,
            person_created_at,
            group0_properties,
            group1_properties,
            group2_properties,
            group3_properties,
            group4_properties,
            group0_created_at,
            group1_created_at,
            group2_created_at,
            group3_created_at,
            group4_created_at,
            person_mode,
            historical_migration,
            coalesce(captured_at, created_at) AS captured_at,
            _timestamp,
            _offset,
            _partition,
            consumer_breadcrumbs
        FROM
        (
            SELECT
                *,
                _timestamp,
                _offset,
                _partition,
                arrayMap(i -> (_headers.value[i]), arrayFilter(i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'), arrayEnumerate(_headers.name))) AS consumer_breadcrumbs,
                JSONCleanPostHogEvent(properties, person_properties) AS cleaned
            FROM ${var.database}.kafka_events_json_native_json
        ) AS source
    )
    SETTINGS input_format_try_infer_dates = 0, input_format_try_infer_datetimes = 0
  SQL
  override = try(var.overrides["events_json_table_mv"], {})

  depends_on = [
    module.kafka_events_json_native_json,
    module.writable_events_json,
  ]
}

module "kafka_events_json_native_json" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_events_json_native_json")
  database = var.database
  name     = "kafka_events_json_native_json"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_events_json_native_json', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_events_json'"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "person_created_at", type = "DateTime64(3)" },
    { name = "person_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group0_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group1_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group2_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group3_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group4_properties", type = "String", codec = "ZSTD(3)" },
    { name = "group0_created_at", type = "DateTime64(3)" },
    { name = "group1_created_at", type = "DateTime64(3)" },
    { name = "group2_created_at", type = "DateTime64(3)" },
    { name = "group3_created_at", type = "DateTime64(3)" },
    { name = "group4_created_at", type = "DateTime64(3)" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "historical_migration", type = "Bool" },
    { name = "dmat_string_0", type = "Nullable(String)" },
    { name = "dmat_string_1", type = "Nullable(String)" },
    { name = "dmat_string_2", type = "Nullable(String)" },
    { name = "dmat_string_3", type = "Nullable(String)" },
    { name = "dmat_string_4", type = "Nullable(String)" },
    { name = "dmat_string_5", type = "Nullable(String)" },
    { name = "dmat_string_6", type = "Nullable(String)" },
    { name = "dmat_string_7", type = "Nullable(String)" },
    { name = "dmat_string_8", type = "Nullable(String)" },
    { name = "dmat_string_9", type = "Nullable(String)" },
    { name = "captured_at", type = "Nullable(DateTime64(6, 'UTC'))" },
  ]
  override = try(var.overrides["kafka_events_json_native_json"], {})
}
