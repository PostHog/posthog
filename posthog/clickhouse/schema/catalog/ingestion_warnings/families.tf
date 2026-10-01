module "ingestion_warnings_v2_family" {
  source = "../../lib/table_family"

  name     = "ingestion_warnings_v2_distributed"
  database = var.database
  layout   = "global"
  columns  = local.ingestion_warnings_v2_columns
  storage = {
    partition_by = "toYYYYMM(timestamp)"
    order_by     = "(team_id, type, timestamp)"
    ttl          = var.ttl ? "toDateTime(timestamp) + toIntervalDay(90)" : null
  }
  routing = {
    read  = true
    write = false
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_ingestion_warnings"
    consumer_group = "clickhouse_ingestion_warnings_v2"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "source", type = "LowCardinality(String)" },
      { name = "type", type = "String" },
      { name = "details", type = "String" },
      { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    ]
    settings = {}
  }
  mv_select = <<-SQL
team_id,
    source,
    type,
    details,
    timestamp,
    _timestamp,
    _offset,
    _partition
  SQL
  mv_target = "${var.database}.ingestion_warnings_v2"
  deployment = merge({
    cluster          = "aux"
    kafka_collection = "warpstream_ingestion"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["ingestion_warnings_v2", "ingestion_warnings_v2_distributed", "ingestion_warnings_v2_mv", "kafka_ingestion_warnings_v2"], name) }
  })
  names = { storage = "ingestion_warnings_v2", mv = "ingestion_warnings_v2_mv", kafka = "kafka_ingestion_warnings_v2" }
}

module "sharded_ingestion_warnings_family" {
  source = "../../lib/table_family"

  name     = "ingestion_warnings"
  database = var.database
  columns  = local.sharded_ingestion_warnings_columns
  storage = {
    partition_by = "toYYYYMMDD(timestamp)"
    order_by     = "(team_id, toHour(timestamp), type, source, timestamp)"
  }
  routing = {
    read_columns  = local.sharded_ingestion_warnings_columns
    write_columns = local.sharded_ingestion_warnings_columns
  }
  sharding_key = "rand()"
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["sharded_ingestion_warnings", "ingestion_warnings", "writable_ingestion_warnings"], name) }
  })
}
