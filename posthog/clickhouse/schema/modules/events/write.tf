# Distributed tables that inserts go through.

module "writable_events" {
  source = "../../lib/table"

  enabled  = local.write && !contains(var.exclude, "writable_events")
  database = var.database
  name     = "writable_events"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_events', sipHash64(distinct_id))"
  columns = concat(local.kafka_events_json_columns, [
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
  ])
  override = try(var.overrides["writable_events"], {})
}
