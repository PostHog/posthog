SELECT
  distinct_id,
  person_id,
  team_id,
  coalesce(_sign, if(is_deleted = 0, 1, -1)) AS _sign,
  _timestamp,
  _offset
FROM posthog.kafka_person_distinct_id
