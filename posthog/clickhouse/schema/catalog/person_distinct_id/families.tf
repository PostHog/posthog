module "person_distinct_id_family" {
  source = "../../lib/table_family"

  name     = "person_distinct_id"
  database = var.database
  layout   = "global"
  columns = [
    { name = "distinct_id", type = "String", comment = "skip_0003_fill_person_distinct_id2" },
    { name = "person_id", type = "UUID" },
    { name = "team_id", type = "Int64" },
    { name = "_sign", type = "Int8", default_expression = "1" },
    { name = "is_deleted", type = "Int8", alias_expression = "if(_sign = -1, 1, 0)" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
  storage = {
    engine      = "CollapsingMergeTree"
    engine_args = ["_sign"]
    order_by    = "(team_id, distinct_id, person_id)"
  }
  routing = {
    write = false
  }
  kafka = {
    topic          = "clickhouse_person_unique_id"
    consumer_group = "group1"
    arguments      = "settings"
    columns = [
      { name = "distinct_id", type = "String" },
      { name = "person_id", type = "UUID" },
      { name = "team_id", type = "Int64" },
      { name = "_sign", type = "Nullable(Int8)" },
      { name = "is_deleted", type = "Nullable(Int8)" },
    ]
    settings = {}
  }
  mv_select = <<-SQL
distinct_id,
    person_id,
    team_id,
    coalesce(_sign, if(is_deleted = 0, 1, -1)) AS _sign,
    _timestamp,
    _offset
  SQL
  mv_target = "${var.database}.person_distinct_id"
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["person_distinct_id", "person_distinct_id_mv", "kafka_person_distinct_id"], name) }
  })
}

module "person_distinct_id2_family" {
  source = "../../lib/table_family"

  name     = "person_distinct_id2"
  database = var.database
  layout   = "global"
  columns  = local.person_distinct_id2_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, distinct_id)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_person_distinct_id2", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_person_distinct_id"
    consumer_group = "group1"
    arguments      = "settings"
    columns        = local.kafka_person_distinct_id2_columns
    settings       = {}
  }
  mv_select = <<-SQL
team_id,
    distinct_id,
    person_id,
    is_deleted,
    version,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["person_distinct_id2", "writable_person_distinct_id2", "person_distinct_id2_mv", "kafka_person_distinct_id2"], name) }
  })
}
