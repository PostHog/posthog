# Tables that hold data, and the materialized views between them.

module "events_recent_json_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(local.deployment.exclude, "events_recent_json_mv")
  database = var.database
  name     = "events_recent_json_mv"
  to_table = "${var.database}.writable_events_recent"
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
        _timestamp,
        _offset
    FROM ${var.database}.sharded_events
  SQL
  override = try(local.deployment.overrides["events_recent_json_mv"], {})

  depends_on = [
    module.sharded_events_recent_family,
  ]
}
