module "groups_family" {
  source = "../../lib/table_family"

  name     = "groups"
  database = var.database
  layout   = "global"
  columns = concat(local.writable_groups_columns, [
    { name = "is_deleted", type = "Bool" },
  ])
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["_timestamp"]
    order_by    = "(team_id, group_type_index, group_key)"
    indexes = [
      { name = "is_deleted_idx", expression = "is_deleted", type = "minmax", granularity = 1 },
    ]
  }
  routing = {
    write_columns = local.writable_groups_columns
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_groups"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_groups_columns
    settings       = {}
  }
  mv_select = <<-SQL
group_type_index,
    group_key,
    created_at,
    team_id,
    group_properties,
    _timestamp,
    _offset
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["groups", "writable_groups", "groups_mv", "kafka_groups"], name) }
  })
}
