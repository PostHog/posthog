# Feature flag evaluation events. Every data node runs these, cloud included, so
# they sit in the shared layer rather than roles/data/local: a layer only the local
# node composes cannot describe a table the cloud nodes also have.
database "posthog" {
  # Mirrors the events column set minus events' materialized property columns, with
  # the full properties JSON kept as the source of truth. The typed property columns
  # below carry their DEFAULT expression only on sharded_flag_evaluations; the
  # Distributed proxy repeats them plain, because a Distributed engine computes
  # nothing.
  table "_flag_evaluations_columns" {
    abstract = true
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "LowCardinality(String)"
    }
    column "properties" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_id" {
      type = "UUID"
    }
    column "person_properties" {
      type = "String"
    }
    column "group0_properties" {
      type = "String"
    }
    column "group1_properties" {
      type = "String"
    }
    column "group2_properties" {
      type = "String"
    }
    column "group3_properties" {
      type = "String"
    }
    column "group4_properties" {
      type = "String"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "timestamp"
    }
    column "$group_0" {
      type    = "String"
      comment = "column_materializer::$group_0"
    }
    column "$group_1" {
      type    = "String"
      comment = "column_materializer::$group_1"
    }
    column "$group_2" {
      type    = "String"
      comment = "column_materializer::$group_2"
    }
    column "$group_3" {
      type    = "String"
      comment = "column_materializer::$group_3"
    }
    column "$group_4" {
      type    = "String"
      comment = "column_materializer::$group_4"
    }
    column "flag_key" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag"
    }
    column "response" {
      type    = "LowCardinality(String)"
      comment = "column_materializer::properties::$feature_flag_response"
    }
    column "session_id" {
      type    = "String"
      comment = "column_materializer::properties::$session_id"
    }
    column "request_id" {
      type    = "String"
      comment = "column_materializer::properties::$feature_flag_request_id"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
  }

  table "flag_evaluations" {
    extend = "_flag_evaluations_columns"
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_flag_evaluations"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "sharded_flag_evaluations" {
    order_by     = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    extend = "_flag_evaluations_columns"
    patch_column "$group_0" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
    }
    patch_column "$group_1" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
    }
    patch_column "$group_2" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
    }
    patch_column "$group_3" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
    }
    patch_column "$group_4" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
    }
    patch_column "flag_key" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', '')"
    }
    patch_column "response" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^\"|\"$', '')"
    }
    patch_column "session_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
    }
    patch_column "request_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_request_id'), '^\"|\"$', '')"
    }
    index "distinct_id_idx" {
      expr        = "distinct_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "person_id_idx" {
      expr        = "person_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "session_id_idx" {
      expr        = "session_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "request_id_idx" {
      expr        = "request_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "inserted_at_idx" {
      expr        = "inserted_at"
      type        = "minmax"
      granularity = 1
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.flag_evaluations"
      replica_name = "{replica}"
    }
  }
}
