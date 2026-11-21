# Feature flag evaluation reads. The column set and the Distributed read table sit in
# the shared layer because every data node has the read table, cloud included. A layer
# only the local node composes cannot describe a table the cloud nodes also have.
# The flags role composes this file too.
# The storage table is in roles/coshared/flag_evaluations_data: prod data nodes read it
# through the flags cluster and do not store it.
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
      type    = "String"
      default = "'{}'"
    }
    column "person_created_at" {
      type = "DateTime64(3)"
    }
    column "inserted_at" {
      type    = "DateTime64(6, 'UTC')"
      default = "timestamp"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
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
    # ALTER TABLE ADD COLUMN appended the two map columns, so the live tables list
    # them after _partition. Add new columns at the end to keep the declared order
    # equal to the live order.
    column "properties_group_custom" {
      type = "Map(String, String)"
    }
    column "person_properties_map_custom" {
      type = "Map(String, String)"
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
}
