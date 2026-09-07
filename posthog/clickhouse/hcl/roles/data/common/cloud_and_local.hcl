# Objects both the local data node and every cloud data cluster run, identically.
# They sit here rather than in roles/data/local so the cloud stacks can compose
# them: a layer only the local node composes cannot describe a shared table.
database "posthog" {
  table "adhoc_events_deletion" {
    order_by = ["team_id", "uuid"]
    ttl      = "deleted_at + toIntervalMonth(3) WHERE is_deleted = 1"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "uuid" {
      type = "UUID"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now64()"
    }
    column "deleted_at" {
      type = "DateTime"
    }
    column "is_deleted" {
      type    = "UInt8"
      default = "0"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path          = "/clickhouse/tables/noshard/posthog.adhoc_events_deletion"
      replica_name      = "{replica}-{shard}"
      version_column    = "deleted_at"
      is_deleted_column = "is_deleted"
    }
  }

  table "app_metrics2" {
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "LowCardinality(String)"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "count" {
      type = "SimpleAggregateFunction(sum, Int64)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_app_metrics2"
      sharding_key    = "rand()"
    }
  }

  table "channel_definition" {
    order_by = ["domain", "kind"]
    settings = {
      index_granularity = "8192"
    }
    column "domain" {
      type = "String"
    }
    column "kind" {
      type = "String"
    }
    column "domain_type" {
      type = "Nullable(String)"
    }
    column "type_if_paid" {
      type = "Nullable(String)"
    }
    column "type_if_organic" {
      type = "Nullable(String)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.channel_definition"
      replica_name = "{replica}-{shard}"
    }
  }

  table "cohort_membership" {
    order_by = ["team_id", "cohort_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "UUID"
    }
    column "status" {
      type = "Enum8('entered'=1, 'left'=2)"
    }
    column "last_updated" {
      type    = "DateTime64(6)"
      default = "now64()"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.cohort_membership"
      replica_name   = "{replica}-{shard}"
      version_column = "last_updated"
    }
  }

  table "distinct_id_usage" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "minute" {
      type = "DateTime"
    }
    column "event_count" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_distinct_id_usage"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "distributed_posthog_document_embeddings_text_embedding_3_large_3072" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "distributed_posthog_document_embeddings_text_embedding_3_small_1536" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "duplicate_events" {
    order_by     = ["team_id", "distinct_id", "event", "inserted_at"]
    partition_by = "toYYYYMMDD(inserted_at)"
    ttl          = "inserted_at + toIntervalDay(7)"
    settings = {
      index_granularity = "512"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "event" {
      type = "String"
    }
    column "source_uuid" {
      type = "UUID"
    }
    column "duplicate_uuid" {
      type = "UUID"
    }
    column "similarity_score" {
      type = "Float64"
    }
    column "dedup_type" {
      type = "LowCardinality(String)"
    }
    column "is_confirmed" {
      type = "UInt8"
    }
    column "reason" {
      type = "Nullable(String)"
    }
    column "version" {
      type = "String"
    }
    column "different_property_count" {
      type = "UInt32"
    }
    column "properties_similarity" {
      type = "Float64"
    }
    column "source_message" {
      type = "String"
    }
    column "duplicate_message" {
      type = "String"
    }
    column "distinct_fields" {
      type = "Array(Tuple(field_name String, original_value String, new_value String))"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
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
    index "kafka_timestamp_minmax_duplicate_events" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.duplicate_events"
      replica_name = "{replica}-{shard}"
    }
  }

  table "error_tracking_issue_fingerprint_overrides" {
    order_by = ["team_id", "fingerprint"]
    settings = {
      index_granularity = "512"
    }
    column "team_id" {
      type = "Int64"
    }
    column "fingerprint" {
      type = "String"
    }
    column "issue_id" {
      type = "UUID"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
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
    index "kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.error_tracking_issue_fingerprint_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  view "events_batch_export_recent" {
    query = <<SQL
SELECT
  team_id AS team_id,
  timestamp AS timestamp,
  event AS event,
  distinct_id AS distinct_id,
  toString(uuid) AS uuid,
  inserted_at AS _inserted_at,
  created_at AS created_at,
  elements_chain AS elements_chain,
  toString(person_id) AS person_id,
  nullIf(properties, '') AS properties,
  nullIf(person_properties, '') AS person_properties,
  nullIf(JSONExtractString(properties, '$set'), '') AS set,
  nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
FROM posthog.events_recent
PREWHERE
  (events_recent.inserted_at >= {interval_start: DateTime64}) AND (events_recent.inserted_at < {interval_end: DateTime64})
WHERE
  (team_id = {team_id: Int64})
AND
  ((length({include_events: Array(String)}) = 0) OR (event IN ({include_events: Array(String)})))
AND
  ((length({exclude_events: Array(String)}) = 0) OR (event NOT IN ({exclude_events: Array(String)})))
ORDER BY _inserted_at ASC, event ASC
LIMIT 1 BY team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid)
SETTINGS
  optimize_aggregation_in_order = 1
SQL

  }

  table "exchange_rate" {
    order_by = ["date", "currency"]
    settings = {
      index_granularity = "8192"
    }
    column "currency" {
      type = "String"
    }
    column "date" {
      type = "Date"
    }
    column "rate" {
      type = "Decimal(18, 10)"
    }
    column "version" {
      type    = "UInt32"
      default = "toUnixTimestamp(now())"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.exchange_rate"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "experiment_exposures_preaggregated" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "entity_id" {
      type = "String"
    }
    column "variant" {
      type = "String"
    }
    column "first_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "exposure_event_uuid" {
      type = "UUID"
    }
    column "exposure_session_id" {
      type = "String"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_experiment_exposures_preaggregated"
      sharding_key    = "cityHash64(entity_id)"
    }
  }

  table "heatmaps" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "x" {
      type = "Int16"
    }
    column "y" {
      type = "Int16"
    }
    column "scale_factor" {
      type = "Int16"
    }
    column "viewport_width" {
      type = "Int16"
    }
    column "viewport_height" {
      type = "Int16"
    }
    column "pointer_target_fixed" {
      type = "Bool"
    }
    column "current_url" {
      type = "String"
    }
    column "type" {
      type = "LowCardinality(String)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_heatmaps"
      sharding_key    = "cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp))))"
    }
  }

  table "llma_metrics_daily" {
    order_by     = ["team_id", "date", "metric_name"]
    partition_by = "toYYYYMM(date)"
    settings = {
      index_granularity = "8192"
    }
    column "date" {
      type = "Date"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "metric_name" {
      type = "String"
    }
    column "metric_value" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.llma_metrics_daily"
      replica_name = "{replica}-{shard}"
    }
  }

  table "log_entries" {
    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_log_entries"
      sharding_key    = "rand()"
    }
  }

  table "performance_events" {
    column "uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "pageview_id" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "time_origin" {
      type = "DateTime64(3, 'UTC')"
    }
    column "entry_type" {
      type = "LowCardinality(String)"
    }
    column "name" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "current_url" {
      type = "String"
    }
    column "start_time" {
      type = "Float64"
    }
    column "duration" {
      type = "Float64"
    }
    column "redirect_start" {
      type = "Float64"
    }
    column "redirect_end" {
      type = "Float64"
    }
    column "worker_start" {
      type = "Float64"
    }
    column "fetch_start" {
      type = "Float64"
    }
    column "domain_lookup_start" {
      type = "Float64"
    }
    column "domain_lookup_end" {
      type = "Float64"
    }
    column "connect_start" {
      type = "Float64"
    }
    column "secure_connection_start" {
      type = "Float64"
    }
    column "connect_end" {
      type = "Float64"
    }
    column "request_start" {
      type = "Float64"
    }
    column "response_start" {
      type = "Float64"
    }
    column "response_end" {
      type = "Float64"
    }
    column "decoded_body_size" {
      type = "Int64"
    }
    column "encoded_body_size" {
      type = "Int64"
    }
    column "initiator_type" {
      type = "LowCardinality(String)"
    }
    column "next_hop_protocol" {
      type = "LowCardinality(String)"
    }
    column "render_blocking_status" {
      type = "LowCardinality(String)"
    }
    column "response_status" {
      type = "Int64"
    }
    column "transfer_size" {
      type = "Int64"
    }
    column "largest_contentful_paint_element" {
      type = "String"
    }
    column "largest_contentful_paint_render_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_load_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_size" {
      type = "Float64"
    }
    column "largest_contentful_paint_id" {
      type = "String"
    }
    column "largest_contentful_paint_url" {
      type = "String"
    }
    column "dom_complete" {
      type = "Float64"
    }
    column "dom_content_loaded_event" {
      type = "Float64"
    }
    column "dom_interactive" {
      type = "Float64"
    }
    column "load_event_end" {
      type = "Float64"
    }
    column "load_event_start" {
      type = "Float64"
    }
    column "redirect_count" {
      type = "Int64"
    }
    column "navigation_type" {
      type = "LowCardinality(String)"
    }
    column "unload_event_end" {
      type = "Float64"
    }
    column "unload_event_start" {
      type = "Float64"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_performance_events"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  table "person_distinct_id" {
    order_by = ["team_id", "distinct_id", "person_id"]
    settings = {
      index_granularity = "8192"
    }
    column "distinct_id" {
      type    = "String"
      comment = "skip_0003_fill_person_distinct_id2"
    }
    column "person_id" {
      type = "UUID"
    }
    column "team_id" {
      type = "Int64"
    }
    column "_sign" {
      type    = "Int8"
      default = "1"
    }
    column "is_deleted" {
      type  = "Int8"
      alias = "if(_sign = -1, 1, 0)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_collapsing_merge_tree" {
      zoo_path     = "/clickhouse/tables/noshard/posthog.person_distinct_id"
      replica_name = "{replica}-{shard}"
      sign_column  = "_sign"
    }
  }

  table "person_overrides" {
    order_by     = ["team_id", "old_person_id"]
    partition_by = "toYYYYMM(oldest_event)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int32"
    }
    column "old_person_id" {
      type = "UUID"
    }
    column "override_person_id" {
      type = "UUID"
    }
    column "merged_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "oldest_event" {
      type = "DateTime64(6, 'UTC')"
    }
    column "created_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "version" {
      type = "Int32"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/noshard/posthog.person_overrides"
      replica_name   = "{replica}-{shard}"
      version_column = "version"
    }
  }

  table "pg_embeddings" {
    order_by = ["team_id", "domain", "id"]
    settings = {
      index_granularity = "512"
    }
    column "domain" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "id" {
      type = "String"
    }
    column "vector" {
      type = "Array(Float32)"
    }
    column "text" {
      type = "String"
    }
    column "properties" {
      type  = "String"
      codec = "ZSTD(3)"
    }
    column "timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "is_deleted" {
      type = "UInt8"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path          = "/clickhouse/tables/noshard/posthog.pg_embeddings"
      replica_name      = "{replica}-{shard}"
      version_column    = "timestamp"
      is_deleted_column = "is_deleted"
    }
  }

  view "posthog_document_embeddings_union_view" {
    query = <<SQL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition,
  'text-embedding-3-small-1536' AS model_name
FROM posthog.distributed_posthog_document_embeddings_text_embedding_3_small_1536
UNION ALL
SELECT
  team_id,
  product,
  document_type,
  rendering,
  document_id,
  timestamp,
  inserted_at,
  content,
  metadata,
  embedding,
  _timestamp,
  _offset,
  _partition,
  'text-embedding-3-large-3072' AS model_name
FROM posthog.distributed_posthog_document_embeddings_text_embedding_3_large_3072
SQL

  }

  table "preaggregation_results" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "uniq_exact_state" {
      type = "AggregateFunction(uniqExact, UUID)"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_preaggregation_results"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  view "raw_sessions_v" {
    query = <<SQL
SELECT
  session_id_v7,
  fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(session_id_v7, 80)), 1000)) AS session_timestamp,
  team_id,
  argMaxMerge(distinct_id) AS distinct_id,
  min(min_timestamp) AS min_timestamp,
  max(max_timestamp) AS max_timestamp,
  max(max_inserted_at) AS max_inserted_at,
  arrayDistinct(arrayFlatten(groupArray(urls))) AS urls,
  argMinMerge(entry_url) AS entry_url,
  argMaxMerge(end_url) AS end_url,
  argMaxMerge(last_external_click_url) AS last_external_click_url,
  argMinMerge(initial_browser) AS initial_browser,
  argMinMerge(initial_browser_version) AS initial_browser_version,
  argMinMerge(initial_os) AS initial_os,
  argMinMerge(initial_os_version) AS initial_os_version,
  argMinMerge(initial_device_type) AS initial_device_type,
  argMinMerge(initial_viewport_width) AS initial_viewport_width,
  argMinMerge(initial_viewport_height) AS initial_viewport_height,
  argMinMerge(initial_geoip_country_code) AS initial_geoip_country_code,
  argMinMerge(initial_geoip_subdivision_1_code) AS initial_geoip_subdivision_1_code,
  argMinMerge(initial_geoip_subdivision_1_name) AS initial_geoip_subdivision_1_name,
  argMinMerge(initial_geoip_subdivision_city_name) AS initial_geoip_subdivision_city_name,
  argMinMerge(initial_geoip_time_zone) AS initial_geoip_time_zone,
  argMinMerge(initial_utm_source) AS initial_utm_source,
  argMinMerge(initial_utm_campaign) AS initial_utm_campaign,
  argMinMerge(initial_utm_medium) AS initial_utm_medium,
  argMinMerge(initial_utm_term) AS initial_utm_term,
  argMinMerge(initial_utm_content) AS initial_utm_content,
  argMinMerge(initial_referring_domain) AS initial_referring_domain,
  argMinMerge(initial_gclid) AS initial_gclid,
  argMinMerge(initial_gad_source) AS initial_gad_source,
  argMinMerge(initial_gclsrc) AS initial_gclsrc,
  argMinMerge(initial_dclid) AS initial_dclid,
  argMinMerge(initial_gbraid) AS initial_gbraid,
  argMinMerge(initial_wbraid) AS initial_wbraid,
  argMinMerge(initial_fbclid) AS initial_fbclid,
  argMinMerge(initial_msclkid) AS initial_msclkid,
  argMinMerge(initial_twclid) AS initial_twclid,
  argMinMerge(initial_li_fat_id) AS initial_li_fat_id,
  argMinMerge(initial_mc_cid) AS initial_mc_cid,
  argMinMerge(initial_igshid) AS initial_igshid,
  argMinMerge(initial_ttclid) AS initial_ttclid,
  argMinMerge(initial__kx) AS initial__kx,
  argMinMerge(initial_irclid) AS initial_irclid,
  sum(pageview_count) AS pageview_count,
  uniqMerge(pageview_uniq) AS pageview_uniq,
  sum(autocapture_count) AS autocapture_count,
  uniqMerge(autocapture_uniq) AS autocapture_uniq,
  sum(screen_count) AS screen_count,
  uniqMerge(screen_uniq) AS screen_uniq,
  max(maybe_has_session_replay) AS maybe_has_session_replay,
  uniqUpToMerge(1)(page_screen_autocapture_uniq_up_to) AS page_screen_autocapture_uniq_up_to,
  argMinMerge(vitals_lcp) AS vitals_lcp
FROM posthog.raw_sessions
GROUP BY
  session_id_v7, team_id
SQL

  }

  table "session_replay_embeddings" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_embeddings"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  table "sharded_app_metrics2" {
    order_by     = ["team_id", "app_source", "app_source_id", "instance_id", "toStartOfHour(timestamp)", "metric_kind", "metric_name"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "app_source" {
      type = "LowCardinality(String)"
    }
    column "app_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "metric_kind" {
      type = "LowCardinality(String)"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "count" {
      type = "SimpleAggregateFunction(sum, Int64)"
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
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.sharded_app_metrics2"
      replica_name = "{replica}"
    }
  }

  table "sharded_distinct_id_usage" {
    order_by     = ["team_id", "minute", "distinct_id"]
    partition_by = "toYYYYMMDD(minute)"
    ttl          = "toDate(minute) + toIntervalDay(7)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "minute" {
      type = "DateTime"
    }
    column "event_count" {
      type = "UInt64"
    }
    engine "replicated_summing_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.distinct_id_usage"
      replica_name = "{replica}"
      sum_columns  = ["event_count"]
    }
  }

  table "sharded_experiment_exposures_preaggregated" {
    order_by     = ["team_id", "job_id", "entity_id", "breakdown_value"]
    partition_by = "toYYYYMMDD(expires_at)"
    ttl          = "expires_at"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "entity_id" {
      type = "String"
    }
    column "variant" {
      type = "String"
    }
    column "first_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_exposure_time" {
      type = "DateTime64(6, 'UTC')"
    }
    column "exposure_event_uuid" {
      type = "UUID"
    }
    column "exposure_session_id" {
      type = "String"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "Date"
      default = "today() + toIntervalDay(7)"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.experiment_exposures_preaggregated"
      replica_name   = "{replica}"
      version_column = "computed_at"
    }
  }

  table "sharded_heatmaps" {
    order_by     = ["type", "team_id", "toDate(timestamp)", "current_url", "viewport_width"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity = "8192"
    }
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "x" {
      type = "Int16"
    }
    column "y" {
      type = "Int16"
    }
    column "scale_factor" {
      type = "Int16"
    }
    column "viewport_width" {
      type = "Int16"
    }
    column "viewport_height" {
      type = "Int16"
    }
    column "pointer_target_fixed" {
      type = "Bool"
    }
    column "current_url" {
      type = "String"
    }
    column "type" {
      type = "LowCardinality(String)"
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.heatmaps"
      replica_name = "{replica}"
    }
  }

  table "sharded_log_entries" {
    order_by     = ["team_id", "log_source", "log_source_id", "instance_id", "timestamp"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(90)"
    settings = {
      index_granularity   = "1024"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "UInt64"
    }
    column "log_source" {
      type = "LowCardinality(String)"
    }
    column "log_source_id" {
      type = "String"
    }
    column "instance_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "level" {
      type = "LowCardinality(String)"
    }
    column "message" {
      type = "String"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_log_entries"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "sharded_performance_events" {
    order_by     = ["team_id", "toDate(timestamp)", "session_id", "pageview_id", "timestamp"]
    partition_by = "toYYYYMM(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalWeek(3)"
    settings = {
      index_granularity = "8192"
    }
    column "uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "pageview_id" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "time_origin" {
      type = "DateTime64(3, 'UTC')"
    }
    column "entry_type" {
      type = "LowCardinality(String)"
    }
    column "name" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "current_url" {
      type = "String"
    }
    column "start_time" {
      type = "Float64"
    }
    column "duration" {
      type = "Float64"
    }
    column "redirect_start" {
      type = "Float64"
    }
    column "redirect_end" {
      type = "Float64"
    }
    column "worker_start" {
      type = "Float64"
    }
    column "fetch_start" {
      type = "Float64"
    }
    column "domain_lookup_start" {
      type = "Float64"
    }
    column "domain_lookup_end" {
      type = "Float64"
    }
    column "connect_start" {
      type = "Float64"
    }
    column "secure_connection_start" {
      type = "Float64"
    }
    column "connect_end" {
      type = "Float64"
    }
    column "request_start" {
      type = "Float64"
    }
    column "response_start" {
      type = "Float64"
    }
    column "response_end" {
      type = "Float64"
    }
    column "decoded_body_size" {
      type = "Int64"
    }
    column "encoded_body_size" {
      type = "Int64"
    }
    column "initiator_type" {
      type = "LowCardinality(String)"
    }
    column "next_hop_protocol" {
      type = "LowCardinality(String)"
    }
    column "render_blocking_status" {
      type = "LowCardinality(String)"
    }
    column "response_status" {
      type = "Int64"
    }
    column "transfer_size" {
      type = "Int64"
    }
    column "largest_contentful_paint_element" {
      type = "String"
    }
    column "largest_contentful_paint_render_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_load_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_size" {
      type = "Float64"
    }
    column "largest_contentful_paint_id" {
      type = "String"
    }
    column "largest_contentful_paint_url" {
      type = "String"
    }
    column "dom_complete" {
      type = "Float64"
    }
    column "dom_content_loaded_event" {
      type = "Float64"
    }
    column "dom_interactive" {
      type = "Float64"
    }
    column "load_event_end" {
      type = "Float64"
    }
    column "load_event_start" {
      type = "Float64"
    }
    column "redirect_count" {
      type = "Int64"
    }
    column "navigation_type" {
      type = "LowCardinality(String)"
    }
    column "unload_event_end" {
      type = "Float64"
    }
    column "unload_event_start" {
      type = "Float64"
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
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.performance_events"
      replica_name = "{replica}"
    }
  }

  table "sharded_posthog_document_embeddings_buffer" {
    order_by     = ["inserted_at", "model_name", "cityHash64(document_id)"]
    partition_by = "toDate(inserted_at)"
    ttl          = "inserted_at + toIntervalDay(1)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "model_name" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_buffer"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  table "sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
    order_by     = ["team_id", "toDate(timestamp)", "product", "document_type", "rendering", "cityHash64(document_id)"]
    partition_by = "toMonday(timestamp)"
    ttl          = "timestamp + toIntervalMonth(3)"
    settings = {
      index_granularity   = "512"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    index "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_large_3072" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "embedding_idx_l2" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'L2Distance', 3072)"
      granularity = 100000000
    }
    index "embedding_idx_cosine" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'cosineDistance', 3072)"
      granularity = 100000000
    }
    constraint "embedding_dimension_check" {
      check = "length(embedding) = 3072"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  table "sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
    order_by     = ["team_id", "toDate(timestamp)", "product", "document_type", "rendering", "cityHash64(document_id)"]
    partition_by = "toMonday(timestamp)"
    ttl          = "timestamp + toIntervalMonth(3)"
    settings = {
      index_granularity   = "512"
      ttl_only_drop_parts = "1"
    }
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    index "kafka_timestamp_minmax_sharded_posthog_document_embeddings_text_embedding_3_small_1536" {
      expr        = "_timestamp"
      type        = "minmax"
      granularity = 3
    }
    index "embedding_idx_l2" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'L2Distance', 1536)"
      granularity = 100000000
    }
    index "embedding_idx_cosine" {
      expr        = "embedding"
      type        = "vector_similarity('hnsw', 'cosineDistance', 1536)"
      granularity = 100000000
    }
    constraint "embedding_dimension_check" {
      check = "length(embedding) = 1536"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      replica_name   = "{replica}"
      version_column = "inserted_at"
    }
  }

  table "sharded_preaggregation_results" {
    order_by     = ["team_id", "job_id", "time_window_start", "breakdown_value"]
    partition_by = "toYYYYMM(time_window_start)"
    ttl          = "expires_at"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    column "breakdown_value" {
      type = "Array(String)"
    }
    column "uniq_exact_state" {
      type = "AggregateFunction(uniqExact, UUID)"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.preaggregation_results"
      replica_name = "{replica}"
    }
  }

  table "sharded_session_replay_embeddings" {
    order_by     = ["toDate(generation_timestamp)", "team_id", "session_id"]
    partition_by = "toYYYYMM(generation_timestamp)"
    ttl          = "toDate(generation_timestamp) + toIntervalYear(1)"
    settings = {
      index_granularity = "512"
    }
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/{shard}/posthog.session_replay_embeddings"
      replica_name = "{replica}"
    }
  }

  table "usage_report_events_preagg" {
    column "date" {
      type = "Date"
    }
    column "team_id" {
      type = "Int64"
    }
    column "person_mode" {
      type = "LowCardinality(String)"
    }
    column "lib" {
      type = "LowCardinality(String)"
    }
    column "event" {
      type = "String"
    }
    column "distinct_events_unique" {
      type = "AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64))"
    }
    column "event_count" {
      type = "AggregateFunction(sum, UInt64)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_usage_report_events_preagg"
      sharding_key    = "sipHash64(date)"
    }
  }

  table "web_overview_preaggregated" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "uniq_sessions_state" {
      type = "AggregateFunction(uniq, String)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_duration_state" {
      type = "AggregateFunction(avg, Float64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Int64)"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_overview_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_stats_paths_preaggregated" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "breakdown_value" {
      type = "String"
    }
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Nullable(Float64))"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_paths_preaggregated"
      sharding_key    = "sipHash64(job_id)"
    }
  }

  table "web_stats_paths_preaggregated_pathkey" {
    column "team_id" {
      type = "Int64"
    }
    column "job_id" {
      type = "UUID"
    }
    column "time_window_start" {
      type = "DateTime64(6, 'UTC')"
    }
    column "breakdown_value" {
      type = "String"
    }
    column "uniq_users_state" {
      type = "AggregateFunction(uniq, UUID)"
    }
    column "sum_pageviews_state" {
      type = "AggregateFunction(sum, Int64)"
    }
    column "avg_bounce_state" {
      type = "AggregateFunction(avg, Nullable(Float64))"
    }
    column "computed_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now()"
    }
    column "expires_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "now() + toIntervalDay(7)"
    }
    engine "distributed" {
      cluster_name    = "aux"
      remote_database = "posthog"
      remote_table    = "sharded_web_stats_paths_preaggregated_pathkey"
      sharding_key    = "sipHash64(breakdown_value)"
    }
  }

  table "writable_posthog_document_embeddings_text_embedding_3_large_3072" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_large_3072"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "writable_posthog_document_embeddings_text_embedding_3_small_1536" {
    column "team_id" {
      type = "Int64"
    }
    column "product" {
      type = "LowCardinality(String)"
    }
    column "document_type" {
      type = "LowCardinality(String)"
    }
    column "rendering" {
      type = "LowCardinality(String)"
    }
    column "document_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3, 'UTC')"
    }
    column "inserted_at" {
      type = "DateTime64(3, 'UTC')"
    }
    column "content" {
      type    = "String"
      default = "''"
    }
    column "metadata" {
      type    = "String"
      default = "'{}'"
    }
    column "embedding" {
      type = "Array(Float64)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_text_embedding_3_small_1536"
      sharding_key    = "cityHash64(document_id)"
    }
  }

  table "writable_session_replay_embeddings" {
    column "session_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "embeddings" {
      type = "Array(Float32)"
    }
    column "generation_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      default = "now('UTC')"
    }
    column "source_type" {
      type = "LowCardinality(String)"
    }
    column "input" {
      type = "String"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_replay_embeddings"
      sharding_key    = "sipHash64(session_id)"
    }
  }

  table "writeable_performance_events" {
    column "uuid" {
      type = "UUID"
    }
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "pageview_id" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "time_origin" {
      type = "DateTime64(3, 'UTC')"
    }
    column "entry_type" {
      type = "LowCardinality(String)"
    }
    column "name" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "current_url" {
      type = "String"
    }
    column "start_time" {
      type = "Float64"
    }
    column "duration" {
      type = "Float64"
    }
    column "redirect_start" {
      type = "Float64"
    }
    column "redirect_end" {
      type = "Float64"
    }
    column "worker_start" {
      type = "Float64"
    }
    column "fetch_start" {
      type = "Float64"
    }
    column "domain_lookup_start" {
      type = "Float64"
    }
    column "domain_lookup_end" {
      type = "Float64"
    }
    column "connect_start" {
      type = "Float64"
    }
    column "secure_connection_start" {
      type = "Float64"
    }
    column "connect_end" {
      type = "Float64"
    }
    column "request_start" {
      type = "Float64"
    }
    column "response_start" {
      type = "Float64"
    }
    column "response_end" {
      type = "Float64"
    }
    column "decoded_body_size" {
      type = "Int64"
    }
    column "encoded_body_size" {
      type = "Int64"
    }
    column "initiator_type" {
      type = "LowCardinality(String)"
    }
    column "next_hop_protocol" {
      type = "LowCardinality(String)"
    }
    column "render_blocking_status" {
      type = "LowCardinality(String)"
    }
    column "response_status" {
      type = "Int64"
    }
    column "transfer_size" {
      type = "Int64"
    }
    column "largest_contentful_paint_element" {
      type = "String"
    }
    column "largest_contentful_paint_render_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_load_time" {
      type = "Float64"
    }
    column "largest_contentful_paint_size" {
      type = "Float64"
    }
    column "largest_contentful_paint_id" {
      type = "String"
    }
    column "largest_contentful_paint_url" {
      type = "String"
    }
    column "dom_complete" {
      type = "Float64"
    }
    column "dom_content_loaded_event" {
      type = "Float64"
    }
    column "dom_interactive" {
      type = "Float64"
    }
    column "load_event_end" {
      type = "Float64"
    }
    column "load_event_start" {
      type = "Float64"
    }
    column "redirect_count" {
      type = "Int64"
    }
    column "navigation_type" {
      type = "LowCardinality(String)"
    }
    column "unload_event_end" {
      type = "Float64"
    }
    column "unload_event_start" {
      type = "Float64"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_performance_events"
      sharding_key    = "sipHash64(session_id)"
    }
  }
}
