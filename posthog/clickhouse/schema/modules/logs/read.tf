# Distributed tables, views and dictionaries that queries read from.

module "log_attributes_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "log_attributes_distributed")
  database = var.database
  name     = "log_attributes_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'log_attributes3')"
  columns  = local.log_attributes3_columns
  override = try(var.overrides["log_attributes_distributed"], {})
}

module "logs" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs")
  database = var.database
  name     = "logs"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs32')"
  columns  = local.logs32_columns
  override = try(var.overrides["logs"], {})
}

module "logs_billing_metrics_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs_billing_metrics_distributed")
  database = var.database
  name     = "logs_billing_metrics_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs_billing_metrics')"
  columns  = local.logs_billing_metrics_columns
  override = try(var.overrides["logs_billing_metrics_distributed"], {})
}

module "logs_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs_distributed")
  database = var.database
  name     = "logs_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs34')"
  columns  = local.logs34_columns
  override = try(var.overrides["logs_distributed"], {})
}

module "logs_kafka_metrics_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs_kafka_metrics_distributed")
  database = var.database
  name     = "logs_kafka_metrics_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs_kafka_metrics')"
  columns  = local.logs_kafka_metrics_columns
  override = try(var.overrides["logs_kafka_metrics_distributed"], {})
}

module "logs_pattern_buckets_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs_pattern_buckets_distributed")
  database = var.database
  name     = "logs_pattern_buckets_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs_pattern_buckets')"
  columns  = local.logs_pattern_buckets_columns
  override = try(var.overrides["logs_pattern_buckets_distributed"], {})
}

module "logs_volume_buckets_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "logs_volume_buckets_distributed")
  database = var.database
  name     = "logs_volume_buckets_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'logs_volume_buckets')"
  columns  = local.logs_volume_buckets_columns
  override = try(var.overrides["logs_volume_buckets_distributed"], {})
}
