# Tables that hold data, and the materialized views between them.

module "exchange_rate" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "exchange_rate")
  database = var.database
  name     = "exchange_rate"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.exchange_rate${var.zk_path_suffix}', '{replica}-{shard}', version)"
  order_by = "(date, currency)"
  columns = [
    { name = "currency", type = "String" },
    { name = "date", type = "Date" },
    { name = "rate", type = "Decimal(18, 10)" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  override = try(var.overrides["exchange_rate"], {})
}
