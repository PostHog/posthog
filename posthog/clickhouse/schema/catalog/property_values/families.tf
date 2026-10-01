module "property_values_family" {
  source = "../../lib/table_family"

  name     = "property_values_distributed"
  database = var.database
  layout   = "global"
  columns  = local.property_values_columns
  storage = {
    engine   = "AggregatingMergeTree"
    order_by = "(team_id, property_type, property_key, property_value)"
    ttl      = var.ttl ? "last_seen + toIntervalDay(30)" : null
    indexes = [
      { name = "idx_property_value_ngrambf", expression = "lower(property_value)", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    ]
  }
  routing = {
    read         = true
    write        = false
    read_columns = local.property_values_columns
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_property_values"
    consumer_group = "clickhouse_property_values"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "property_type", type = "LowCardinality(String)" },
      { name = "property_key", type = "String" },
      { name = "property_value", type = "String" },
      { name = "property_count", type = "UInt64" },
    ]
    settings = { kafka_num_consumers = "1", kafka_thread_per_consumer = "1" }
  }
  mv_select = <<-SQL
team_id,
    property_type,
    property_key,
    property_value,
    property_count,
    coalesce(_timestamp, now()) AS last_seen
  SQL
  mv_target = "${var.database}.property_values"
  deployment = merge({
    cluster          = "aux"
    kafka_collection = "warpstream_ingestion"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["property_values", "property_values_distributed", "property_values_mv", "kafka_property_values"], name) }
  })
  names = { storage = "property_values", mv = "property_values_mv", kafka = "kafka_property_values" }
}
