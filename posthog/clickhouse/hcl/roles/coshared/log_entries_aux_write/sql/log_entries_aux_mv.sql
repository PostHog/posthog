SELECT
    team_id,
    log_source,
    log_source_id,
    instance_id,
    timestamp,
    level,
    message,
    _timestamp,
    _offset
FROM kafka_log_entries_aux
WHERE toDate(timestamp) <= today()
