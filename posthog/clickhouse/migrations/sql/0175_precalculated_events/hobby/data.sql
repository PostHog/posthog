DROP TABLE IF EXISTS behavioral_cohorts_matches

DROP TABLE IF EXISTS sharded_behavioral_cohorts_matches

CREATE TABLE IF NOT EXISTS sharded_precalculated_events
(
    team_id Int64,
    date Date,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_precalculated_events', '{replica}', _timestamp)
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, condition, date, distinct_id, uuid)

CREATE TABLE IF NOT EXISTS precalculated_events
(
    team_id Int64,
    date Date,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_precalculated_events', sipHash64(distinct_id))

CREATE TABLE IF NOT EXISTS cohort_membership
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6) DEFAULT now64()
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.cohort_membership', '{replica}-{shard}', last_updated)
ORDER BY (team_id, cohort_id, person_id)
