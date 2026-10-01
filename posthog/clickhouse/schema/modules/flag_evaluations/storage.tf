# Tables that hold data, and the materialized views between them.

module "sharded_flag_evaluations" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "sharded_flag_evaluations")
  database     = var.database
  name         = "sharded_flag_evaluations"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.flag_evaluations${var.zk_path_suffix}', '{replica}')"
  partition_by = "toYYYYMM(timestamp)"
  order_by     = "(team_id, flag_key, toDate(timestamp), cityHash64(distinct_id))"
  ttl          = var.ttl ? "toDate(timestamp) + toIntervalDay(90)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "LowCardinality(String)" },
    { name = "properties", type = "String" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "person_id", type = "UUID" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "timestamp" },
    { name = "$group_0", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')", comment = "column_materializer::$group_0" },
    { name = "$group_1", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')", comment = "column_materializer::$group_1" },
    { name = "$group_2", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')", comment = "column_materializer::$group_2" },
    { name = "$group_3", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')", comment = "column_materializer::$group_3" },
    { name = "$group_4", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')", comment = "column_materializer::$group_4" },
    { name = "flag_key", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag" },
    { name = "response", type = "LowCardinality(String)", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag_response" },
    { name = "session_id", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')", comment = "column_materializer::properties::$session_id" },
    { name = "request_id", type = "String", default_expression = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^\"|\"$', '')", comment = "column_materializer::properties::$feature_flag_request_id" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "_partition", type = "UInt64" },
  ]
  indexes = [
    { name = "distinct_id_idx", expression = "distinct_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "person_id_idx", expression = "person_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "session_id_idx", expression = "session_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "request_id_idx", expression = "request_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "inserted_at_idx", expression = "inserted_at", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["sharded_flag_evaluations"], {})
}
