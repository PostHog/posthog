module "exchange_rate_family" {
  source = "../../lib/table_family"

  name     = "exchange_rate"
  database = var.database
  layout   = "global"
  columns = [
    { name = "currency", type = "String" },
    { name = "date", type = "Date" },
    { name = "rate", type = "Decimal(18, 10)" },
    { name = "version", type = "UInt32", default_expression = "toUnixTimestamp(now())" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(date, currency)"
  }
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["exchange_rate"], name) }
  })
}
