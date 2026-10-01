module "person_family" {
  source = "../../lib/table_family"

  name     = "person"
  database = var.database
  layout   = "global"
  columns  = local.person_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, id)"
    indexes = [
      { name = "kafka_timestamp_minmax_person", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
    unmanaged_columns = ["^p?mat_"]
    unmanaged_indexes = ["^(minmax|bloom_filter|bloom_filter_lower|ngram_bf_lower)_p?mat_"]
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_person"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_person_columns
    settings       = {}
  }
  mv_select = <<-SQL
id,
    created_at,
    team_id,
    properties,
    is_identified,
    is_deleted,
    version,
    last_seen_at,
    _timestamp,
    _offset
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["person", "writable_person", "person_mv", "kafka_person"], name) }
  })
}
