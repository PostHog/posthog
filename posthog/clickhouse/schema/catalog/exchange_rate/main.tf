variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "dictionary_user" {
  description = "User the dictionaries connect to their source as."
  type        = string
  default     = "default"
}

variable "dictionary_password" {
  description = "Password of `dictionary_user`."
  type        = string
  default     = ""
  sensitive   = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

module "exchange_rate_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

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
  deployment = local.deployment
}

# Distributed tables, views and dictionaries that queries read from.

module "exchange_rate_dict" {
  source = "../../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "exchange_rate_dict")
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
