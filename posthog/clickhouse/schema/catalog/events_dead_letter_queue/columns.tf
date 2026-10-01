# Column lists that more than one object uses.

locals {
  kafka_events_dead_letter_queue_columns = [
    { name = "id", type = "UUID" },
    { name = "event_uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "properties", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "team_id", type = "Int64" },
    { name = "elements_chain", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "ip", type = "String" },
    { name = "site_url", type = "String" },
    { name = "now", type = "DateTime64(6, 'UTC')" },
    { name = "raw_payload", type = "String" },
    { name = "error_timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "error_location", type = "String" },
    { name = "error", type = "String" },
    { name = "tags", type = "Array(String)" },
  ]

  events_dead_letter_queue_columns = concat(local.kafka_events_dead_letter_queue_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ])
}
