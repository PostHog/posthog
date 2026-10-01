module "person_distinct_id_overrides_family" {
  source = "../../lib/table_family"

  name     = "person_distinct_id_overrides"
  database = var.database
  layout   = "global"
  columns  = local.person_distinct_id_overrides_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, distinct_id)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_person_distinct_id_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    write = true
  }
  sharding_key = ""
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["person_distinct_id_overrides", "writable_person_distinct_id_overrides"], name) }
  })
}
