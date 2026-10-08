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
  kafka_events_json_columns = [
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
  ]
}

module "sharded_events_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "events"
  database = var.database
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String", codec = "ZSTD(3)" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "$group_0", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')", comment = "column_materializer::$group_0" },
    { name = "$group_1", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')", comment = "column_materializer::$group_1" },
    { name = "$group_2", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')", comment = "column_materializer::$group_2" },
    { name = "$group_3", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')", comment = "column_materializer::$group_3" },
    { name = "$group_4", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')", comment = "column_materializer::$group_4" },
    { name = "$window_id", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^\"|\"$', '')", comment = "column_materializer::$window_id" },
    { name = "$session_id", type = "String", materialized_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')", comment = "column_materializer::$session_id" },
    { name = "inserted_at", type = "Nullable(DateTime64(6, 'UTC'))", default_expression = "now64()" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "elements_chain_href", type = "String", materialized_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_ids", type = "Array(String)", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", materialized_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))" },
    { name = "properties_group_custom", type = "Map(String, String)", materialized_expression = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))", codec = "ZSTD(1)" },
    { name = "properties_group_feature_flags", type = "Map(String, String)", materialized_expression = "mapSort(mapFilter((key, _) -> (key LIKE '$feature/%'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))", codec = "ZSTD(1)" },
    { name = "is_deleted", type = "Bool" },
    { name = "person_properties_map_custom", type = "Map(String, String)", materialized_expression = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))", codec = "ZSTD(1)" },
    { name = "$session_id_uuid", type = "Nullable(UInt128)", materialized_expression = "toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "properties_group_ai", type = "Map(String, String)", materialized_expression = "mapSort(mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))", codec = "ZSTD(1)" },
    { name = "mat_$ai_session_id", type = "Nullable(String)", materialized_expression = "JSONExtract(properties, '$ai_session_id', 'Nullable(String)')" },
    { name = "mat_$ai_is_error", type = "Nullable(String)", materialized_expression = "JSONExtract(properties, '$ai_is_error', 'Nullable(String)')" },
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
    { name = "historical_migration", type = "Bool" },
    { name = "mat_$ai_prompt_name", type = "Nullable(String)", materialized_expression = "JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')" },
    { name = "properties_map_ephemeral", type = "Map(String, String)" },
    { name = "person_properties_map_ephemeral", type = "Map(String, String)" },
    { name = "mat_$ai_experiment_id", type = "Nullable(String)", default_expression = "JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')" },
    { name = "elements_chain", type = "String" },
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
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "mat_$ai_trace_id", type = "Nullable(String)", materialized_expression = "JSONExtract(properties, '$ai_trace_id', 'Nullable(String)')" },
  ]
  storage = {
    engine       = "ReplacingMergeTree"
    engine_args  = ["_timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))"
    sample_by    = "cityHash64(distinct_id)"
    indexes = [
      { name = "minmax_inserted_at", expression = "coalesce(inserted_at, _timestamp)", type = "minmax", granularity = 1 },
      { name = "properties_group_custom_keys_bf", expression = "mapKeys(properties_group_custom)", type = "bloom_filter", granularity = 1 },
      { name = "properties_group_custom_values_bf", expression = "mapValues(properties_group_custom)", type = "bloom_filter", granularity = 1 },
      { name = "properties_group_feature_flags_keys_bf", expression = "mapKeys(properties_group_feature_flags)", type = "bloom_filter", granularity = 1 },
      { name = "properties_group_feature_flags_values_bf", expression = "mapValues(properties_group_feature_flags)", type = "bloom_filter", granularity = 1 },
      { name = "person_properties_map_custom_keys_bf", expression = "mapKeys(person_properties_map_custom)", type = "bloom_filter", granularity = 1 },
      { name = "person_properties_map_custom_values_bf", expression = "mapValues(person_properties_map_custom)", type = "bloom_filter", granularity = 1 },
      { name = "properties_group_ai_keys_bf", expression = "mapKeys(properties_group_ai)", type = "bloom_filter", granularity = 1 },
      { name = "properties_group_ai_values_bf", expression = "mapValues(properties_group_ai)", type = "bloom_filter", granularity = 1 },
      { name = "bloom_filter_$ai_trace_id", expression = "`mat_$ai_trace_id`", type = "bloom_filter(0.001)", granularity = 2 },
      { name = "bloom_filter_$ai_session_id", expression = "`mat_$ai_session_id`", type = "bloom_filter", granularity = 1 },
      { name = "minmax_$ai_session_id", expression = "`mat_$ai_session_id`", type = "minmax", granularity = 1 },
      { name = "set_$ai_is_error", expression = "`mat_$ai_is_error`", type = "set(7)", granularity = 1 },
      { name = "bloom_filter_distinct_id", expression = "distinct_id", type = "bloom_filter", granularity = 1 },
      { name = "minmax_sharded_events_timestamp", expression = "timestamp", type = "minmax", granularity = 1 },
      { name = "bloom_filter_$ai_prompt_name", expression = "`mat_$ai_prompt_name`", type = "bloom_filter", granularity = 1 },
      { name = "minmax_$ai_prompt_name", expression = "`mat_$ai_prompt_name`", type = "minmax", granularity = 1 },
      { name = "bloom_filter_$ai_experiment_id", expression = "`mat_$ai_experiment_id`", type = "bloom_filter", granularity = 1 },
      { name = "minmax_$ai_experiment_id", expression = "`mat_$ai_experiment_id`", type = "minmax", granularity = 1 },
      { name = "minmax_$session_id_uuid", expression = "`$session_id_uuid`", type = "minmax", granularity = 1 },
      { name = "bloom_filter_$session_id", expression = "nullIf(nullIf(`$session_id`, ''), 'null')", type = "bloom_filter", granularity = 1 },
      { name = "minmax_$group_0", expression = "`$group_0`", type = "minmax", granularity = 1 },
      { name = "minmax_$group_1", expression = "`$group_1`", type = "minmax", granularity = 1 },
      { name = "minmax_$group_2", expression = "`$group_2`", type = "minmax", granularity = 1 },
      { name = "minmax_$group_3", expression = "`$group_3`", type = "minmax", granularity = 1 },
      { name = "minmax_$group_4", expression = "`$group_4`", type = "minmax", granularity = 1 },
      { name = "minmax_$window_id", expression = "`$window_id`", type = "minmax", granularity = 1 },
      { name = "minmax_$session_id", expression = "`$session_id`", type = "minmax", granularity = 1 },
      { name = "kafka_timestamp_minmax_sharded_events", expression = "_timestamp", type = "minmax", granularity = 3 },
      { name = "is_deleted_idx", expression = "is_deleted", type = "minmax", granularity = 1 },
      { name = "minmax_historical_migration", expression = "historical_migration", type = "minmax", granularity = 1 },
    ]
    unmanaged_columns = ["^p?mat_"]
    unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"]
  }
  routing = {
    read_columns = [
      { name = "uuid", type = "UUID" },
      { name = "event", type = "String" },
      { name = "properties", type = "String", codec = "ZSTD(3)" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "created_at", type = "DateTime64(6, 'UTC')" },
      { name = "$group_0", type = "String", comment = "column_materializer::$group_0" },
      { name = "$group_1", type = "String", comment = "column_materializer::$group_1" },
      { name = "$group_2", type = "String", comment = "column_materializer::$group_2" },
      { name = "$group_3", type = "String", comment = "column_materializer::$group_3" },
      { name = "$group_4", type = "String", comment = "column_materializer::$group_4" },
      { name = "$window_id", type = "String", comment = "column_materializer::$window_id" },
      { name = "$session_id", type = "String", comment = "column_materializer::$session_id" },
      { name = "inserted_at", type = "Nullable(DateTime64(6, 'UTC'))", default_expression = "now64()" },
      { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
      { name = "elements_chain_href", type = "String", comment = "column_materializer::elements_chain::href" },
      { name = "elements_chain_texts", type = "Array(String)", comment = "column_materializer::elements_chain::texts" },
      { name = "elements_chain_ids", type = "Array(String)", comment = "column_materializer::elements_chain::ids" },
      { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", comment = "column_materializer::elements_chain::elements" },
      { name = "properties_group_custom", type = "Map(String, String)" },
      { name = "properties_group_feature_flags", type = "Map(String, String)" },
      { name = "is_deleted", type = "Bool" },
      { name = "person_properties_map_custom", type = "Map(String, String)" },
      { name = "$session_id_uuid", type = "Nullable(UInt128)" },
      { name = "consumer_breadcrumbs", type = "Array(String)" },
      { name = "properties_group_ai", type = "Map(String, String)" },
      { name = "mat_$ai_session_id", type = "Nullable(String)", comment = "column_materializer::properties::$ai_session_id" },
      { name = "mat_$ai_is_error", type = "Nullable(String)", comment = "column_materializer::properties::$ai_is_error" },
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
      { name = "historical_migration", type = "Bool" },
      { name = "mat_$ai_prompt_name", type = "Nullable(String)", comment = "column_materializer::properties::$ai_prompt_name" },
      { name = "elements_chain", type = "String" },
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
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "mat_$ai_trace_id", type = "Nullable(String)", comment = "column_materializer::properties::$ai_trace_id" },
      { name = "mat_$ai_experiment_id", type = "Nullable(String)", comment = "column_materializer::properties::$ai_experiment_id" },
    ]
    write_columns = concat(local.kafka_events_json_columns, [
      { name = "_timestamp", type = "DateTime" },
      { name = "_offset", type = "UInt64" },
      { name = "consumer_breadcrumbs", type = "Array(String)" },
    ])
  }
  sharding_key = "sipHash64(distinct_id)"
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.events"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    overrides = {
      "sharded_events"  = try(local.deployment.overrides["sharded_events"], {})
      "events"          = merge({ unmanaged_columns = ["^p?mat_"], unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"] }, try(local.deployment.overrides["events"], {}))
      "writable_events" = try(local.deployment.overrides["writable_events"], {})
    }
  })
  names = { mv = "events_json_mv", kafka = "kafka_events_json" }
}

# Distributed tables, views and dictionaries that queries read from.


module "events_batch_export" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "events_batch_export")
  database = var.database
  name     = "events_batch_export"
  query    = <<-SQL
    SELECT
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        coalesce(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM ${var.database}.events
    PREWHERE (coalesce(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end:DateTime64})
    WHERE (team_id = {team_id:Int64}) AND (events.timestamp >= ({interval_start:DateTime64} - toIntervalDay({lookback_days:Int32}))) AND (events.timestamp < ({interval_end:DateTime64} + toIntervalDay(1))) AND ((length({include_events:Array(String)}) = 0) OR (event IN ({include_events:Array(String)}))) AND ((length({exclude_events:Array(String)}) = 0) OR (event NOT IN ({exclude_events:Array(String)})))
    ORDER BY
        _inserted_at ASC,
        event ASC
    LIMIT 1 BY
        team_id,
        event,
        cityHash64(events.distinct_id),
        cityHash64(events.uuid)
    SETTINGS optimize_aggregation_in_order = 1
  SQL
  override = try(local.deployment.overrides["events_batch_export"], {})

  depends_on = [
    module.sharded_events_family,
  ]
}

module "events_batch_export_backfill" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "events_batch_export_backfill")
  database = var.database
  name     = "events_batch_export_backfill"
  query    = <<-SQL
    SELECT
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        timestamp AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM ${var.database}.events
    WHERE (team_id = {team_id:Int64}) AND (events.timestamp >= {interval_start:DateTime64}) AND (events.timestamp < {interval_end:DateTime64}) AND ((length({include_events:Array(String)}) = 0) OR (event IN ({include_events:Array(String)}))) AND ((length({exclude_events:Array(String)}) = 0) OR (event NOT IN ({exclude_events:Array(String)})))
    ORDER BY
        _inserted_at ASC,
        event ASC
    LIMIT 1 BY
        team_id,
        event,
        cityHash64(events.distinct_id),
        cityHash64(events.uuid)
    SETTINGS optimize_aggregation_in_order = 1
  SQL
  override = try(local.deployment.overrides["events_batch_export_backfill"], {})

  depends_on = [
    module.sharded_events_family,
  ]
}

module "events_batch_export_unbounded" {
  source = "../../lib/view"
  node   = var.node

  enabled  = contains(var.objects, "events_batch_export_unbounded")
  database = var.database
  name     = "events_batch_export_unbounded"
  query    = <<-SQL
    SELECT
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        coalesce(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM ${var.database}.events
    PREWHERE (coalesce(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}) AND (coalesce(events.inserted_at, events._timestamp) < {interval_end:DateTime64})
    WHERE (team_id = {team_id:Int64}) AND ((length({include_events:Array(String)}) = 0) OR (event IN ({include_events:Array(String)}))) AND ((length({exclude_events:Array(String)}) = 0) OR (event NOT IN ({exclude_events:Array(String)})))
    ORDER BY
        _inserted_at ASC,
        event ASC
    LIMIT 1 BY
        team_id,
        event,
        cityHash64(events.distinct_id),
        cityHash64(events.uuid)
    SETTINGS optimize_aggregation_in_order = 1
  SQL
  override = try(local.deployment.overrides["events_batch_export_unbounded"], {})

  depends_on = [
    module.sharded_events_family,
  ]
}

module "kafka_events_json" {
  source = "../../lib/table"
  node   = var.node

  deployment = local.deployment

  enabled  = contains(var.objects, "kafka_events_json")
  database = var.database
  name     = "kafka_events_json"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'group1', kafka_skip_broken_messages = 100, kafka_topic_list = 'clickhouse_events_json'"
  columns  = local.kafka_events_json_columns
  override = try(local.deployment.overrides["kafka_events_json"], {})
}

module "events_json_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "events_json_mv")
  database = var.database
  name     = "events_json_mv"
  to_table = "${var.database}.writable_events"
  query    = <<-SQL
    SELECT
        uuid,
        event,
        properties,
        timestamp,
        team_id,
        distinct_id,
        elements_chain,
        created_at,
        person_id,
        person_created_at,
        person_properties,
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
        dmat_string_0,
        dmat_string_1,
        dmat_string_2,
        dmat_string_3,
        dmat_string_4,
        dmat_string_5,
        dmat_string_6,
        dmat_string_7,
        dmat_string_8,
        dmat_string_9,
        _timestamp,
        _offset,
        arrayMap(i -> (_headers.value[i]), arrayFilter(i -> ((_headers.name[i]) = 'kafka-consumer-breadcrumbs'), arrayEnumerate(_headers.name))) AS consumer_breadcrumbs
    FROM ${var.database}.kafka_events_json
  SQL
  override = try(local.deployment.overrides["events_json_mv"], {})

  depends_on = [
    module.kafka_events_json,
    module.sharded_events_family,
  ]
}
