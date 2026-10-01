# Distributed tables, views and dictionaries that queries read from.

module "distributed_events_recent" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "distributed_events_recent")
  database = var.database
  name     = "distributed_events_recent"
  engine   = "Distributed('posthog_primary_replica', '${var.database}', 'sharded_events_recent', sipHash64(distinct_id))"
  columns  = local.sharded_events_recent_columns
  override = try(var.overrides["distributed_events_recent"], {})
}

module "events_batch_export_recent" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "events_batch_export_recent")
  database = var.database
  name     = "events_batch_export_recent"
  query    = <<-SQL
    SELECT
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        inserted_at AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM ${var.database}.events_recent
    PREWHERE (events_recent.inserted_at >= {interval_start:DateTime64}) AND (events_recent.inserted_at < {interval_end:DateTime64})
    WHERE (team_id = {team_id:Int64}) AND ((length({include_events:Array(String)}) = 0) OR (event IN ({include_events:Array(String)}))) AND ((length({exclude_events:Array(String)}) = 0) OR (event NOT IN ({exclude_events:Array(String)})))
    ORDER BY
        _inserted_at ASC,
        event ASC
    LIMIT 1 BY
        team_id,
        event,
        cityHash64(events_recent.distinct_id),
        cityHash64(events_recent.uuid)
    SETTINGS optimize_aggregation_in_order = 1
  SQL
  override = try(var.overrides["events_batch_export_recent"], {})

  depends_on = [
    module.events_recent,
  ]
}

module "events_recent" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "events_recent")
  database = var.database
  name     = "events_recent"
  engine   = "Distributed('posthog_primary_replica', '${var.database}', 'sharded_events_recent', sipHash64(distinct_id))"
  columns  = local.sharded_events_recent_columns
  override = try(var.overrides["events_recent"], {})
}
