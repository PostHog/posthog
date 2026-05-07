CREATE TABLE IF NOT EXISTS sharded_precalculated_person_properties
(
    team_id Int64,
    distinct_id String,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_precalculated_person_properties', '{replica}', _timestamp)
ORDER BY (team_id, condition, distinct_id)

CREATE TABLE IF NOT EXISTS precalculated_person_properties
(
    team_id Int64,
    distinct_id String,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_precalculated_person_properties', sipHash64(distinct_id))
