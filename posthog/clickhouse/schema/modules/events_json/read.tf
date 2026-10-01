# Distributed tables, views and dictionaries that queries read from.

module "events_json" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "events_json")
  database = var.database
  name     = "events_json"
  engine   = "Distributed('posthog', '${var.database}', 'sharded_events_json', sipHash64(distinct_id))"
  columns = concat(local.writable_events_json_columns, [
    { name = "elements_chain_href", type = "String" },
    { name = "elements_chain_texts", type = "Array(String)" },
    { name = "elements_chain_ids", type = "Array(String)" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))" },
  ])
  override = try(var.overrides["events_json"], {})
}
