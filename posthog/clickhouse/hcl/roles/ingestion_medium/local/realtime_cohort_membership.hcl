database "posthog" {
  table "kafka_realtime_cohort_membership" {
    column "type" {
      type = "String"
    }
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "person_id" {
      type = "String"
    }
    column "status" {
      type = "String"
    }
    column "last_updated" {
      type = "String"
    }
    column "run_id" {
      type = "String"
    }
    column "threshold" {
      type = "String"
    }
    column "partitions" {
      type = "UInt16"
    }
    engine "kafka" {
      collection           = "warpstream_ingestion"
      topic_list           = "cohort_membership_changed"
      group_name           = "clickhouse_realtime_cohort_membership"
      format               = "JSONEachRow"
      num_consumers        = 1
      max_block_size       = 100000
      skip_broken_messages = 100
      poll_timeout_ms      = 10000
      flush_interval_ms    = 7500
      thread_per_consumer  = true
    }
  }

  table "writable_realtime_cohort_membership" {
    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "kind" {
      type = "Enum8('member'=0, 'floor'=1)"
    }
    column "person_id" {
      type = "UUID"
    }
    column "floor_run_id" {
      type = "UUID"
    }
    column "floor_partition" {
      type = "UInt16"
    }
    column "in_cohort" {
      type = "UInt8"
    }
    column "version" {
      type = "DateTime64(6, 'UTC')"
    }
    column "floor_partitions" {
      type = "UInt16"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "realtime_cohort_membership"
    }
  }

  materialized_view "realtime_cohort_membership_mv" {
    to_table = "posthog.writable_realtime_cohort_membership"
    query    = <<SQL
SELECT
  team_id,
  cohort_id,
  if(is_floor, 'floor', 'member') AS kind,
  if(
    is_floor,
    toUUID('00000000-0000-0000-0000-000000000000'),
    ifNull(person_uuid, toUUID('00000000-0000-0000-0000-000000000000'))
  ) AS person_id,
  if(
    is_floor,
    ifNull(run_uuid, toUUID('00000000-0000-0000-0000-000000000000')),
    toUUID('00000000-0000-0000-0000-000000000000')
  ) AS floor_run_id,
  if(is_floor, toUInt16(_partition), 0) AS floor_partition,
  toUInt8(status = 'entered') AS in_cohort,
  assumeNotNull(stamp) AS version,
  if(is_floor, partitions, 0) AS floor_partitions
FROM
  (
    SELECT
      team_id,
      cohort_id,
      type = 'sweep_floor' AS is_floor,
      toUUIDOrNull(person_id) AS person_uuid,
      toUUIDOrNull(run_id) AS run_uuid,
      if(is_floor, threshold, last_updated) AS raw_stamp,
      toDateTime64OrNull(raw_stamp, 6, 'UTC') AS stamp,
      status,
      partitions,
      _partition
    FROM posthog.kafka_realtime_cohort_membership
    WHERE type IN ('', 'sweep_floor')
  )
WHERE
  (toString(stamp) = raw_stamp)
AND
  if(
    is_floor,
    (run_uuid IS NOT NULL) AND (partitions > 0),
    (person_uuid IS NOT NULL) AND (status IN ('entered', 'left'))
  )
SQL

    column "team_id" {
      type = "Int64"
    }
    column "cohort_id" {
      type = "Int64"
    }
    column "kind" {
      type = "String"
    }
    column "person_id" {
      type = "UUID"
    }
    column "floor_run_id" {
      type = "UUID"
    }
    column "floor_partition" {
      type = "UInt16"
    }
    column "in_cohort" {
      type = "UInt8"
    }
    column "version" {
      type = "DateTime64(6, 'UTC')"
    }
    column "floor_partitions" {
      type = "UInt16"
    }
  }
}
