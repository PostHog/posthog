locals {
  membership_deployment                 = merge(var.deployment.sharded, try(var.deployment.families.person_group_membership, {}), { overrides = var.overrides })
  membership_dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}

module "person_group_membership" {
  source  = "../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_group_membership"
  database = var.database
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "group_type_index", type = "UInt8" },
    { name = "group_key", type = "String" },
    { name = "distinct_id", type = "String" },
    { name = "first_seen", type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))" },
    { name = "last_seen", type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))" },
  ]
  storage = {
    engine   = "AggregatingMergeTree"
    order_by = "(team_id, group_type_index, group_key, distinct_id)"
    # Wide parts let lightweight deletes rewrite only the row mask. The sort key cannot narrow person lookups.
    settings = "index_granularity = 8192, min_bytes_for_wide_part = 0, min_rows_for_wide_part = 0"
    indexes = [
      { name = "idx_distinct_id", expression = "distinct_id", type = "bloom_filter(0.01)", granularity = 1 },
    ]
  }
  sharding_key = "sipHash64(team_id, group_type_index, group_key)"
  deployment   = local.membership_deployment
}

module "person_group_membership_config" {
  source  = "../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "person_group_membership_config"
  database = var.database
  layout   = "global"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "group_type_index", type = "UInt8" },
    { name = "enabled", type = "UInt8" },
    { name = "version", type = "UInt64" },
  ]
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "team_id"
  }
  routing      = { read = true, write = false }
  names        = { read = "distributed_person_group_membership_config" }
  sharding_key = "sipHash64(team_id)"
  deployment   = local.membership_deployment
}

module "person_group_membership_config_dict" {
  source = "../lib/dictionary"
  node   = var.node

  enabled     = contains(var.objects, "person_group_membership_config_dict")
  database    = var.database
  name        = "person_group_membership_config_dict"
  primary_key = ["team_id"]
  attributes = [
    { name = "team_id", type = "Int64" },
    { name = "group_type_index", type = "UInt8", default_expression = "255" },
    { name = "enabled", type = "UInt8", default_expression = "0" },
  ]
  # Filter after argMax so a newer disabled or invalid row cannot revive an older valid config.
  source_clause = "CLICKHOUSE(QUERY 'SELECT team_id, config.1 AS group_type_index, config.2 AS enabled FROM (SELECT team_id, argMax(tuple(group_type_index, enabled), version) AS config FROM `${var.database}`.distributed_person_group_membership_config GROUP BY team_id) WHERE enabled = 1 AND group_type_index <= 4' USER '${var.dictionary_user}'${local.membership_dictionary_password_clause})"
  layout        = "COMPLEX_KEY_HASHED()"
  lifetime      = "MIN 60 MAX 120"
  override      = try(local.membership_deployment.overrides["person_group_membership_config_dict"], {})
  depends_on    = [module.person_group_membership_config]
}
