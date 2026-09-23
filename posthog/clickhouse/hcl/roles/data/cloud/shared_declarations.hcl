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

}
