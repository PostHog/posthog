module "sharded_tophog_family" {
  source = "../../lib/table_family"

  name     = "tophog"
  database = var.database
  columns  = local.sharded_tophog_columns
  storage = {
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(pipeline, lane, metric, timestamp, key)"
    ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(30)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  sharding_key = "cityHash64(toString(key))"
  kafka = {
    topic     = "clickhouse_tophog"
    arguments = "settings"
    columns   = local.kafka_tophog_columns
    settings  = { date_time_input_format = "'best_effort'", kafka_skip_broken_messages = "100" }
  }
  mv_select = <<-SQL
timestamp,
    metric,
    type,
    key,
    value,
    count,
    pipeline,
    lane,
    labels
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.tophog"
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_tophog", "tophog", "writable_tophog", "tophog_mv", "kafka_tophog"], name) }
  })
}
