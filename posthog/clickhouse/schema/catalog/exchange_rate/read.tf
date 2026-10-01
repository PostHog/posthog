# Distributed tables, views and dictionaries that queries read from.

module "exchange_rate_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "exchange_rate_dict")
  database    = var.database
  name        = "exchange_rate_dict"
  primary_key = ["currency"]
  attributes = [
    { name = "currency", type = "String" },
    { name = "start_date", type = "Date" },
    { name = "end_date", type = "Nullable(Date)" },
    { name = "rate", type = "Decimal64(10)" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT currency, date AS start_date, leadInFrame(date::Nullable(Date), 1, NULL::Nullable(Date)) OVER w AS end_date, argMax(rate, version) AS rate FROM `${var.database}`.`exchange_rate` GROUP BY date, currency WINDOW w AS ( PARTITION BY currency ORDER BY date ASC ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING )')"
  layout        = "COMPLEX_KEY_RANGE_HASHED(RANGE_LOOKUP_STRATEGY 'max')"
  lifetime      = "MIN 3000 MAX 3600"
  range         = "MIN start_date MAX end_date"
  override      = try(local.deployment.overrides["exchange_rate_dict"], {})

  depends_on = [
    module.exchange_rate_family,
  ]
}
