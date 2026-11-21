# Flag evaluation storage. The flags cluster holds it in prod. The local stacks and dev
# keep it on the data node. Extends the _flag_evaluations_columns abstract from
# roles/data/shared, so a node composes that layer first.
database "posthog" {
  table "sharded_flag_evaluations" {
    order_by     = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(92)"
    settings = {
      index_granularity                = "8192"
      materialize_ttl_recalculate_only = "1"
      ttl_only_drop_parts              = "1"
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
    patch_column "properties_group_custom" {
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid', 'epik', 'qclid', 'sccid', 'irclid', '_kx'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
    }
    patch_column "person_properties_map_custom" {
      materialized = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))"
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
    index "properties_group_custom_keys_bf" {
      expr        = "mapKeys(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_custom_values_bf" {
      expr        = "mapValues(properties_group_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "person_properties_map_custom_keys_bf" {
      expr        = "mapKeys(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "person_properties_map_custom_values_bf" {
      expr        = "mapValues(person_properties_map_custom)"
      type        = "bloom_filter"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.flag_evaluations"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
}
