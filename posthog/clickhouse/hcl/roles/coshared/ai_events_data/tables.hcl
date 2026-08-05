# The person / person_distinct_id2 Distributed shims (migration 0240), hosted by
# the ai_events satellite and the local data node. The data node's storage forms
# (kafka meta columns, minmax indexes, ReplacingMergeTree engines) are patch_table
# blocks in roles/data/local.
database "posthog" {
  table "person" {
    column "id" {
      type = "UUID"
    }
    column "created_at" {
      type = "DateTime64(3)"
    }
    column "team_id" {
      type = "Int64"
    }
    column "properties" {
      type = "String"
    }
    column "is_identified" {
      type = "Int8"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "UInt64"
    }
    column "last_seen_at" {
      type = "Nullable(DateTime64(3))"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "person"
    }
  }

  table "person_distinct_id2" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "is_deleted" {
      type = "Int8"
    }
    column "version" {
      type = "Int64"
    }
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "person_distinct_id2"
    }
  }
}
