# The events family: the storage table and its Distributed proxy, both extending the
# _event_base abstract in roles/shared (defined once, per migration.md). Env deltas
# are patch_table blocks: roles/data/local here, overrides/data/<env> in
# posthog-cloud-infra.
database "posthog" {
  table "sharded_events" {
    extend = "_event_base"
    patch_column "properties" {
      codec = "ZSTD(3)"
    }
    patch_column "$group_0" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_0'), '^\"|\"$', '')"
      comment = "column_materializer::$group_0"
    }
    patch_column "$group_1" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_1'), '^\"|\"$', '')"
      comment = "column_materializer::$group_1"
    }
    patch_column "$group_2" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_2'), '^\"|\"$', '')"
      comment = "column_materializer::$group_2"
    }
    patch_column "$group_3" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_3'), '^\"|\"$', '')"
      comment = "column_materializer::$group_3"
    }
    patch_column "$group_4" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$group_4'), '^\"|\"$', '')"
      comment = "column_materializer::$group_4"
    }
    patch_column "$window_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$window_id'), '^\"|\"$', '')"
      comment = "column_materializer::$window_id"
    }
    patch_column "$session_id" {
      default = "replaceRegexpAll(JSONExtractRaw(properties, '$session_id'), '^\"|\"$', '')"
      comment = "column_materializer::$session_id"
    }
    patch_column "elements_chain_href" {
      materialized = "EXTRACT(elements_chain, '(?::|\")href=\"(.*?)\"')"
    }
    patch_column "elements_chain_texts" {
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))"
    }
    patch_column "elements_chain_ids" {
      materialized = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))"
    }
    patch_column "elements_chain_elements" {
      materialized = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\\\.|$|:)'))"
    }
    patch_column "properties_group_custom" {
      materialized = "mapSort(mapFilter((key, _) -> ((key NOT LIKE '$%') AND (key NOT IN ('token', 'distinct_id', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'gad_source', 'gclsrc', 'dclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'twclid', 'li_fat_id', 'mc_cid', 'igshid', 'ttclid', 'rdt_cid'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    patch_column "properties_group_feature_flags" {
      materialized = "mapSort(mapFilter((key, _) -> (key LIKE '$feature/%'), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    patch_column "person_properties_map_custom" {
      materialized = "mapSort(mapFilter((key, _) -> (key NOT LIKE '$%'), CAST(JSONExtractKeysAndValues(person_properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    patch_column "$session_id_uuid" {
      materialized = "toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))"
    }
    patch_column "properties_group_ai" {
      materialized = "mapSort(mapFilter((key, _) -> ((key LIKE '$ai_%') AND (key NOT IN ('$ai_input', '$ai_input_state', '$ai_output', '$ai_output_choices', '$ai_output_state', '$ai_tools'))), CAST(JSONExtractKeysAndValues(properties, 'String'), 'Map(String, String)')))"
      codec        = "ZSTD(1)"
    }
    patch_column "mat_historical_migration" {
      default = "JSONExtract(properties, 'historical_migration', 'Nullable(String)')"
    }
    patch_column "mat_$ai_session_id" {
      materialized = "JSONExtract(properties, '$ai_session_id', 'Nullable(String)')"
    }
    patch_column "mat_$ai_is_error" {
      materialized = "JSONExtract(properties, '$ai_is_error', 'Nullable(String)')"
    }
    patch_column "mat_$ai_prompt_name" {
      materialized = "JSONExtract(properties, '$ai_prompt_name', 'Nullable(String)')"
    }
    column "properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "person_properties_map_ephemeral" {
      type = "Map(String, String)"
    }
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      default = "JSONExtract(properties, '$ai_experiment_id', 'Nullable(String)')"
    }
    order_by     = ["team_id", "toDate(timestamp)", "event", "cityHash64(distinct_id)", "cityHash64(uuid)"]
    partition_by = "toYYYYMM(timestamp)"
    sample_by    = "cityHash64(distinct_id)"
    settings = {
      index_granularity = "8192"
    }
    index "minmax_inserted_at" {
      expr        = "coalesce(inserted_at, _timestamp)"
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
    index "properties_group_feature_flags_keys_bf" {
      expr        = "mapKeys(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_feature_flags_values_bf" {
      expr        = "mapValues(properties_group_feature_flags)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "is_deleted_idx" {
      expr        = "is_deleted"
      type        = "minmax"
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
    index "properties_group_ai_keys_bf" {
      expr        = "mapKeys(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "properties_group_ai_values_bf" {
      expr        = "mapValues(properties_group_ai)"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_$ai_trace_id" {
      expr        = "`mat_$ai_trace_id`"
      type        = "bloom_filter(0.001)"
      granularity = 2
    }
    index "minmax_mat_historical_migration" {
      expr        = "mat_historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_session_id" {
      expr        = "`mat_$ai_session_id`"
      type        = "minmax"
      granularity = 1
    }
    index "set_$ai_is_error" {
      expr        = "`mat_$ai_is_error`"
      type        = "set(7)"
      granularity = 1
    }
    index "bloom_filter_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_sharded_events_timestamp" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_prompt_name" {
      expr        = "`mat_$ai_prompt_name`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_$ai_experiment_id" {
      expr        = "`mat_$ai_experiment_id`"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_$session_id_uuid" {
      expr        = "`$session_id_uuid`"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_$session_id" {
      expr        = "nullIf(nullIf(`$session_id`, ''), 'null')"
      type        = "bloom_filter"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "events" {
    extend = "_event_base"
    patch_column "$group_0" {
      comment = "column_materializer::$group_0"
    }
    patch_column "$group_1" {
      comment = "column_materializer::$group_1"
    }
    patch_column "$group_2" {
      comment = "column_materializer::$group_2"
    }
    patch_column "$group_3" {
      comment = "column_materializer::$group_3"
    }
    patch_column "$group_4" {
      comment = "column_materializer::$group_4"
    }
    patch_column "$window_id" {
      comment = "column_materializer::$window_id"
    }
    patch_column "$session_id" {
      comment = "column_materializer::$session_id"
    }
    patch_column "elements_chain_href" {
      comment = "column_materializer::elements_chain::href"
    }
    patch_column "elements_chain_texts" {
      comment = "column_materializer::elements_chain::texts"
    }
    patch_column "elements_chain_ids" {
      comment = "column_materializer::elements_chain::ids"
    }
    patch_column "elements_chain_elements" {
      comment = "column_materializer::elements_chain::elements"
    }
    patch_column "mat_historical_migration" {
      comment = "column_materializer::properties::historical_migration"
    }
    patch_column "mat_$ai_session_id" {
      comment = "column_materializer::properties::$ai_session_id"
    }
    patch_column "mat_$ai_is_error" {
      comment = "column_materializer::properties::$ai_is_error"
    }
    patch_column "mat_$ai_prompt_name" {
      comment = "column_materializer::properties::$ai_prompt_name"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }
}
