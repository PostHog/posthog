module "events_dead_letter_queue_family" {
  source = "../../lib/table_family"

  name     = "events_dead_letter_queue"
  database = var.database
  layout   = "global"
  columns  = local.events_dead_letter_queue_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(id, event_uuid, distinct_id, team_id)"
    ttl         = var.ttl ? "toDate(_timestamp) + toIntervalWeek(4)" : null
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_events_dead_letter_queue", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  sharding_key = ""
  kafka = {
    topic          = "events_dead_letter_queue"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_events_dead_letter_queue_columns
    settings       = { kafka_skip_broken_messages = "1000" }
  }
  mv_select = <<-SQL
id,
    event_uuid,
    event,
    properties,
    distinct_id,
    team_id,
    elements_chain,
    created_at,
    ip,
    site_url,
    now,
    raw_payload,
    error_timestamp,
    error_location,
    error,
    tags,
    _timestamp,
    _offset
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["events_dead_letter_queue", "writable_events_dead_letter_queue", "events_dead_letter_queue_mv", "kafka_events_dead_letter_queue"], name) }
  })
}
