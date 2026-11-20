# Native-JSON flag evaluation storage. The flags cluster holds it in prod. The local stacks and
# dev keep it on the data node. Extends the _flag_evaluations_json_columns abstract.
database "posthog" {
  table "sharded_flag_evaluations_json" {
    extend       = "_flag_evaluations_json_columns"
    primary_key  = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)"]
    order_by     = ["team_id", "flag_key", "toDate(timestamp)", "cityHash64(distinct_id)", "timestamp", "uuid"]
    partition_by = "clamp(toYYYYMM(timestamp), 202001, 203512)"
    sample_by    = "cityHash64(distinct_id)"
    ttl          = "toDate(timestamp) + toIntervalDay(92)"
    settings = {
      enable_block_number_column                             = "1"
      enable_block_offset_column                             = "1"
      index_granularity                                      = "8192"
      map_serialization_version                              = "with_buckets"
      materialize_ttl_recalculate_only                       = "1"
      object_serialization_version                           = "v3"
      object_shared_data_serialization_version               = "map_with_buckets"
      propagate_types_serialization_versions_to_nested_types = "1"
      string_serialization_version                           = "single_stream"
      ttl_only_drop_parts                                    = "1"
    }
    patch_column "temporary_properties" {
      ttl = "toDateTime(inserted_at) + toIntervalDay(60)"
    }
    patch_column "temporary_properties_null_keys" {
      ttl = "toDateTime(inserted_at) + toIntervalDay(60)"
    }
    patch_column "timestamp" {
      codec = "GCD, Default"
    }
    patch_column "created_at" {
      codec = "GCD, Default"
    }
    patch_column "_timestamp" {
      codec = "T64, Default"
    }
    patch_column "_offset" {
      codec = "T64, Default"
    }
    patch_column "person_created_at" {
      codec = "GCD, Default"
    }
    patch_column "inserted_at" {
      codec = "GCD, Default"
    }
    patch_column "total_event_size" {
      codec = "T64, Default"
    }
    patch_column "captured_at" {
      codec = "GCD, Default"
    }
    patch_column "_partition" {
      codec = "T64, Default"
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
    patch_column "flag_key" {
      default = "toString(properties.`$feature_flag`)"
    }
    patch_column "response" {
      default = "if(has(properties_null_keys, '$feature_flag_response'), 'null', toString(properties.`$feature_flag_response`))"
    }
    patch_column "request_id" {
      default = "toString(temporary_properties.`$feature_flag_request_id`)"
    }
    index "bloom_filter_distinct_id" {
      expr        = "distinct_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_uuid" {
      expr        = "uuid"
      type        = "bloom_filter"
      granularity = 1
    }
    index "bloom_filter_person_id" {
      expr        = "person_id"
      type        = "bloom_filter"
      granularity = 1
    }
    index "minmax_captured_at" {
      expr        = "captured_at"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_kafka_timestamp" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_inserted_at" {
      expr        = "inserted_at"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_timestamp" {
      expr        = "timestamp"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_historical_migration" {
      expr        = "historical_migration"
      type        = "minmax"
      granularity = 1
    }
    index "minmax_created_at" {
      expr        = "created_at"
      type        = "minmax"
      granularity = 1
    }
    index "bloom_filter_session_id" {
      expr        = "properties.`$session_id`"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    index "bloom_filter_request_id" {
      expr        = "request_id"
      type        = "bloom_filter(0.01)"
      granularity = 1
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.flag_evaluations_json"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
}
