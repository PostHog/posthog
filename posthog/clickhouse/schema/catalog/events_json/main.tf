variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {
}

# Column lists that more than one object uses.

locals {
  writable_events_json_columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "JSON(`$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths = 0, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths = 32)" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "elements_chain", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "person_properties", type = "JSON(max_dynamic_paths = 256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)" },
    { name = "group0_created_at", type = "DateTime64(3)" },
    { name = "group1_created_at", type = "DateTime64(3)" },
    { name = "group2_created_at", type = "DateTime64(3)" },
    { name = "group3_created_at", type = "DateTime64(3)" },
    { name = "group4_created_at", type = "DateTime64(3)" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()" },
    { name = "_partition", type = "UInt64" },
  ]
}

module "sharded_events_json_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "events_json"
  database = var.database
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "JSON(`$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths = 0, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths = 32)", ttl = "toDateTime(inserted_at) + toIntervalDay(60)" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))", ttl = "toDateTime(inserted_at) + toIntervalDay(60)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", codec = "GCD, Default" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_timestamp", type = "DateTime", codec = "T64, Default" },
    { name = "_offset", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain", type = "String" },
    { name = "person_id", type = "UUID" },
    { name = "person_properties", type = "JSON(max_dynamic_paths = 256, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group0_created_at", type = "DateTime64(3)" },
    { name = "group1_created_at", type = "DateTime64(3)" },
    { name = "group2_created_at", type = "DateTime64(3)" },
    { name = "group3_created_at", type = "DateTime64(3)" },
    { name = "group4_created_at", type = "DateTime64(3)" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()", codec = "GCD, Default" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32", codec = "T64, Default" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_partition", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain_href", type = "String", materialized_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_ids", type = "Array(String)", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "clamp(toYYYYMM(timestamp), 202001, 203512)"
    primary_key  = "(team_id, toDate(timestamp), event, cityHash64(distinct_id))"
    order_by     = "(team_id, toDate(timestamp), event, cityHash64(distinct_id), timestamp, uuid)"
    sample_by    = "cityHash64(distinct_id)"
    settings     = "enable_block_number_column = 1, enable_block_offset_column = 1, index_granularity = 8192, map_serialization_version = 'with_buckets', object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets', propagate_types_serialization_versions_to_nested_types = 1, string_serialization_version = 'single_stream'"
    indexes = [
      { name = "bloom_filter_distinct_id", expression = "distinct_id", type = "bloom_filter", granularity = 1 },
      { name = "bloom_filter_uuid", expression = "uuid", type = "bloom_filter", granularity = 1 },
      { name = "bloom_filter_person_id", expression = "person_id", type = "bloom_filter", granularity = 1 },
      { name = "minmax_captured_at", expression = "captured_at", type = "minmax", granularity = 1 },
      { name = "minmax_kafka_timestamp", expression = "_timestamp", type = "minmax", granularity = 1 },
      { name = "minmax_inserted_at", expression = "inserted_at", type = "minmax", granularity = 1 },
      { name = "minmax_timestamp", expression = "timestamp", type = "minmax", granularity = 1 },
      { name = "minmax_historical_migration", expression = "historical_migration", type = "minmax", granularity = 1 },
      { name = "minmax_created_at", expression = "created_at", type = "minmax", granularity = 1 },
    ]
  }
  sharding_key = "sipHash64(distinct_id)"
  deployment = merge({
    keeper_path = "/clickhouse/tables/{shard}/${var.database}.events_json"
    cluster     = "posthog"
  }, local.deployment)
}

# Kafka tables and the materialized views that consume them.

module "events_json_table_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "events_json_table_mv")
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
  override = try(local.deployment.overrides["events_json_table_mv"], {})

  depends_on = [
    module.kafka_events_json_native_json,
    module.sharded_events_json_family,
  ]
}

module "kafka_events_json_native_json" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_events_json_native_json")
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
  override = try(local.deployment.overrides["kafka_events_json_native_json"], {})
}
