module "sharded_distinct_id_usage_family" {
  source = "../../lib/table_family"

  name     = "distinct_id_usage"
  database = var.database
  columns  = local.sharded_distinct_id_usage_columns
  storage = {
    engine       = "SummingMergeTree"
    engine_args  = ["(event_count)"]
    partition_by = "toYYYYMMDD(minute)"
    order_by     = "(team_id, minute, distinct_id)"
    ttl          = var.ttl ? "toDate(minute) + toIntervalDay(7)" : null
    settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  }
  sharding_key = "sipHash64(distinct_id)"
  kafka = {
    topic     = "distinct_id_usage_events_json"
    arguments = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "distinct_id", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    ]
    settings = { kafka_skip_broken_messages = "100" }
  }
  mv_select = <<-SQL
team_id,
    distinct_id,
    toStartOfMinute(timestamp) AS minute,
    1 AS event_count
  SQL
  deployment = merge({
    keeper_path      = "/clickhouse/tables/{shard}/${var.database}.distinct_id_usage"
    cluster          = "posthog"
    kafka_collection = "warpstream_ingestion"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_distinct_id_usage", "distinct_id_usage", "writable_distinct_id_usage", "distinct_id_usage_mv", "kafka_distinct_id_usage"], name) }
  })
}
