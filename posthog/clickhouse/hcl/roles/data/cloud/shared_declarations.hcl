# Objects more than one data layer used to declare. The declaration lives here,
# in a layer every consumer composes; a cluster whose shape genuinely differs
# restates it with override = true rather than declaring it a second time.
database "posthog" {
  table "session_recording_events" {
    column "uuid" {
      type = "UUID"
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
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "has_full_snapshot" {
      type    = "Int8"
      comment = "column_materializer::has_full_snapshot"
    }
    column "events_summary" {
      type    = "Array(String)"
      comment = "column_materializer::events_summary"
    }
    column "click_count" {
      type    = "Int8"
      comment = "column_materializer::click_count"
    }
    column "keypress_count" {
      type    = "Int8"
      comment = "column_materializer::keypress_count"
    }
    column "timestamps_summary" {
      type    = "Array(DateTime64(6, 'UTC'))"
      comment = "column_materializer::timestamps_summary"
    }
    column "first_event_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      comment = "column_materializer::first_event_timestamp"
    }
    column "last_event_timestamp" {
      type    = "DateTime64(6, 'UTC')"
      comment = "column_materializer::last_event_timestamp"
    }
    column "urls" {
      type    = "Array(String)"
      comment = "column_materializer::urls"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_session_recording_events"
      sharding_key    = "sipHash64(distinct_id)"
    }
  }

  table "sharded_session_recording_events" {
    order_by     = ["team_id", "toHour(timestamp)", "session_id", "timestamp", "uuid"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(created_at) + toIntervalWeek(3)"
    settings = {
      index_granularity = "512"
    }
    column "uuid" {
      type = "UUID"
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
    column "session_id" {
      type = "String"
    }
    column "window_id" {
      type = "String"
    }
    column "snapshot_data" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "has_full_snapshot" {
      type         = "Int8"
      materialized = "JSONExtractBool(snapshot_data, 'has_full_snapshot')"
      comment      = "column_materializer::has_full_snapshot"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "events_summary" {
      type         = "Array(String)"
      materialized = "JSONExtract(JSON_QUERY(snapshot_data, '$.events_summary[*]'), 'Array(String)')"
    }
    column "click_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 2) AND (JSONExtractInt(x, 'data', 'source') = 2)), events_summary))"
    }
    column "keypress_count" {
      type         = "Int8"
      materialized = "length(arrayFilter(x -> ((JSONExtractInt(x, 'type') = 3) AND (JSONExtractInt(x, 'data', 'source') = 5)), events_summary))"
    }
    column "timestamps_summary" {
      type         = "Array(DateTime64(6, 'UTC'))"
      materialized = "arraySort(arrayMap(x -> toDateTime(JSONExtractInt(x, 'timestamp') / 1000), events_summary))"
    }
    column "first_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('min', timestamps_summary)"
    }
    column "last_event_timestamp" {
      type         = "DateTime64(6, 'UTC')"
      materialized = "arrayReduce('max', timestamps_summary)"
    }
    column "urls" {
      type         = "Array(String)"
      materialized = "arrayFilter(x -> (x != ''), arrayMap(x -> JSONExtractString(x, 'data', 'href'), events_summary))"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/{shard}/posthog.session_recording_events"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  table "writable_events_dead_letter_queue" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
    override = true
    column "id" {
      type = "UUID"
    }
    column "event_uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "elements_chain" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "ip" {
      type = "String"
    }
    column "site_url" {
      type = "String"
    }
    column "now" {
      type = "DateTime64(6, 'UTC')"
    }
    column "raw_payload" {
      type = "String"
    }
    column "error_timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "error_location" {
      type = "String"
    }
    column "error" {
      type = "String"
    }
    column "tags" {
      type = "Array(String)"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "events_dead_letter_queue"
    }
  }

  table "writable_posthog_document_embeddings_buffer" {
    # The ingestion nodes declare this name too, for the table they write through.
    # A data node holds a different object under it, so this restates rather than
    # redeclares.
    override = true
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_posthog_document_embeddings_buffer"
      sharding_key    = "cityHash64(document_id)"
    }
  }
}
