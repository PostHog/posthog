CREATE TABLE IF NOT EXISTS person_static_cohort ON CLUSTER 'posthog'
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_static_cohort', '{replica}-{shard}', _timestamp)
Order By (team_id, cohort_id, person_id, id)
