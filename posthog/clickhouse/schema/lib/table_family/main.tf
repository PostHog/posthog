locals {
  names = {
    storage = coalesce(var.names.storage, var.layout == "sharded" ? "sharded_${var.name}" : var.name)
    read    = coalesce(var.names.read, var.name)
    write   = coalesce(var.names.write, "writable_${var.name}")
    kafka   = coalesce(var.names.kafka, "kafka_${var.name}")
    mv      = coalesce(var.names.mv, "${var.name}_mv")
  }
  enabled = {
    storage = contains(var.deployment.components, "storage") && !contains(var.deployment.exclude, local.names.storage)
    read    = var.layout == "sharded" && contains(var.deployment.components, "read") && !contains(var.deployment.exclude, local.names.read)
    write   = (var.layout == "sharded" || var.kafka != null) && contains(var.deployment.components, "write") && !contains(var.deployment.exclude, local.names.write)
    kafka   = var.kafka != null && contains(var.deployment.components, "ingest") && !contains(var.deployment.exclude, local.names.kafka)
    mv      = var.kafka != null && contains(var.deployment.components, "ingest") && !contains(var.deployment.exclude, local.names.mv)
  }
  keeper_path = coalesce(var.deployment.keeper_path,
    var.layout == "sharded" ? "/clickhouse/tables/{shard}/${var.database}.${local.names.storage}" : "/clickhouse/tables/noshard/${var.database}.${local.names.storage}"
  )
  replica_name = coalesce(var.deployment.replica_name, var.layout == "sharded" ? "{replica}" : "{replica}-{shard}")
  engine_args  = length(var.storage.engine_args) == 0 ? "" : ", ${join(", ", var.storage.engine_args)}"
  read_cluster = coalesce(var.deployment.read_cluster, var.deployment.cluster)
  write_cluster = coalesce(var.deployment.write_cluster,
    var.layout == "global" ? "${var.deployment.cluster}_single_shard" : var.deployment.cluster
  )
  sharding_arg = var.layout == "global" ? "" : ", ${var.sharding_key}"

  # Computed values are read as plain columns; only storage computes and compresses them.
  read_columns = [for column in var.columns : {
    name               = column.name, type = column.type,
    default_expression = column.default_expression, comment = column.comment
  }]
  write_columns = [for column in var.columns : {
    name               = column.name, type = column.type,
    default_expression = column.default_expression, comment = column.comment
  } if column.materialized_expression == null && column.alias_expression == null && column.ephemeral_expression == null]

  kafka_group = var.kafka == null ? "" : coalesce(var.kafka.consumer_group, "clickhouse_${var.name}")
  kafka_settings = var.kafka == null ? {} : merge(var.kafka.settings == null ? {
    kafka_max_block_size       = "100000"
    kafka_num_consumers        = "1"
    kafka_poll_timeout_ms      = "10000"
    kafka_skip_broken_messages = "100"
    kafka_thread_per_consumer  = "1"
  } : var.kafka.settings, var.deployment.kafka_settings)
  kafka_engine = var.kafka == null ? "Kafka" : "Kafka(${var.deployment.kafka_collection}, kafka_topic_list = '${var.kafka.topic}', kafka_group_name = '${local.kafka_group}', kafka_format = '${var.kafka.format}')"
}

module "storage" {
  source = "../table"

  enabled           = local.enabled.storage
  database          = var.database
  name              = local.names.storage
  engine            = "Replicated${var.storage.engine}('${local.keeper_path}', '${local.replica_name}'${local.engine_args})"
  columns           = var.columns
  partition_by      = var.storage.partition_by
  primary_key       = var.storage.primary_key
  order_by          = var.storage.order_by
  sample_by         = var.storage.sample_by
  ttl               = var.storage.ttl
  settings          = var.storage.settings
  indexes           = var.storage.indexes
  projections       = var.storage.projections
  constraints       = var.storage.constraints
  unmanaged_columns = var.storage.unmanaged_columns
  unmanaged_indexes = var.storage.unmanaged_indexes
  override          = try(var.deployment.overrides[local.names.storage], {})
}

module "read" {
  source = "../table"

  enabled    = local.enabled.read
  database   = var.database
  name       = local.names.read
  engine     = "Distributed('${local.read_cluster}', '${var.database}', '${local.names.storage}'${local.sharding_arg})"
  columns    = local.read_columns
  override   = try(var.deployment.overrides[local.names.read], {})
  depends_on = [module.storage]
}

module "write" {
  source = "../table"

  enabled    = local.enabled.write
  database   = var.database
  name       = local.names.write
  engine     = "Distributed('${local.write_cluster}', '${var.database}', '${local.names.storage}'${local.sharding_arg})"
  columns    = local.write_columns
  override   = try(var.deployment.overrides[local.names.write], {})
  depends_on = [module.storage]
}

module "kafka" {
  source = "../table"

  enabled    = local.enabled.kafka
  database   = var.database
  name       = local.names.kafka
  engine     = local.kafka_engine
  columns    = var.kafka == null ? [] : var.kafka.columns
  settings   = length(local.kafka_settings) == 0 ? null : join(", ", [for key in sort(keys(local.kafka_settings)) : "${key} = ${local.kafka_settings[key]}"])
  override   = try(var.deployment.overrides[local.names.kafka], {})
  depends_on = [module.write]
}

module "mv" {
  source = "../materialized_view"

  enabled    = local.enabled.mv
  database   = var.database
  name       = local.names.mv
  to_table   = "${var.database}.${local.names.write}"
  query      = var.kafka == null ? "SELECT 1" : "SELECT ${var.mv_select} FROM ${var.database}.${local.names.kafka}"
  override   = try(var.deployment.overrides[local.names.mv], {})
  depends_on = [module.kafka, module.write]
}

output "objects" {
  description = "Enabled objects for adoption tooling. No credentials are included."
  value = { for kind, enabled in local.enabled : kind => {
    id   = "${var.database}.${local.names[kind]}"
    name = local.names[kind]
    type = kind == "mv" ? "clickhousedbops_materialized_view" : "clickhousedbops_table"
  } if enabled }
  precondition {
    condition     = !local.enabled.mv || (local.enabled.kafka && local.enabled.write)
    error_message = "An ingestion materialized view requires its Kafka source and writable target on the same root."
  }
  precondition {
    condition     = length(setsubtract(keys(var.deployment.overrides), values(local.names))) == 0
    error_message = "An override names an object that is not in this family."
  }
}
