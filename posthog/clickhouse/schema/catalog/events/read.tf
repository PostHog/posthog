# Distributed tables, views and dictionaries that queries read from.


module "events_batch_export" {
  source = "../../lib/view"

  enabled  = local.read && !contains(local.deployment.exclude, "events_batch_export")
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

  enabled  = local.read && !contains(local.deployment.exclude, "events_batch_export_backfill")
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

  enabled  = local.read && !contains(local.deployment.exclude, "events_batch_export_unbounded")
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
