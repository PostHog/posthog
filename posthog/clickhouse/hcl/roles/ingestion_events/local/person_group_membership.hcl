database "posthog" {
  patch_dictionary "person_group_membership_config_dict" {
    source "clickhouse" {
      user = "default"
      query = "SELECT team_id, config.1 AS group_type_index, config.2 AS enabled FROM (SELECT team_id, argMax(tuple(group_type_index, enabled), version) AS config FROM posthog.distributed_person_group_membership_config GROUP BY team_id) WHERE enabled = 1 AND group_type_index <= 4"
    }
  }

  table "kafka_person_group_membership" {
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "clickhouse_events_json"
      group_name           = "clickhouse_person_group_membership"
      format               = "JSONEachRow"
      num_consumers        = 1
      thread_per_consumer  = true
      max_block_size       = 10000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      poll_max_batch_size  = 10000
      flush_interval_ms    = 7500
    }
  }

  materialized_view "person_group_membership_mv" {
    to_table = "posthog.writable_person_group_membership"
    query    = <<SQL
SELECT
  team_id,
  group_type_index,
  replaceRegexpAll(JSONExtractRaw(properties, concat('$group_', toString(group_type_index))), '^"|"$', '') AS group_key,
  distinct_id,
  min(timestamp) AS first_seen,
  max(timestamp) AS last_seen
FROM (
  SELECT
    team_id,
    dictGet('posthog.person_group_membership_config_dict', 'group_type_index', tuple(team_id)) AS group_type_index,
    distinct_id,
    properties,
    timestamp
  FROM posthog.kafka_person_group_membership
  WHERE dictHas('posthog.person_group_membership_config_dict', tuple(team_id)) AND (person_mode != 'propertyless')
)
WHERE notEmpty(group_key)
GROUP BY team_id, group_type_index, group_key, distinct_id
SQL

    column "team_id" {
      type = "Int64"
    }
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "first_seen" {
      type = "DateTime64(6, 'UTC')"
    }
    column "last_seen" {
      type = "DateTime64(6, 'UTC')"
    }
  }
}
