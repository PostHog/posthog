# Distributed tables, views and dictionaries that queries read from.

module "events" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "events")
  database = var.database
  name     = "events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_events', sipHash64(distinct_id))"
  columns = [
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
  unmanaged_columns = ["^p?mat_"]
  unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"]
  override          = try(var.overrides["events"], {})
}

module "events_batch_export" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "events_batch_export")
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
  override = try(var.overrides["events_batch_export"], {})

  depends_on = [
    module.events,
  ]
}

module "events_batch_export_backfill" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "events_batch_export_backfill")
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
  override = try(var.overrides["events_batch_export_backfill"], {})

  depends_on = [
    module.events,
  ]
}

module "events_batch_export_unbounded" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "events_batch_export_unbounded")
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
  override = try(var.overrides["events_batch_export_unbounded"], {})

  depends_on = [
    module.events,
  ]
}
