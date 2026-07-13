SELECT team_id, old_person_id, override_person_id, merged_at, oldest_event, version
FROM posthog.kafka_person_overrides
