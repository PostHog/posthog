CREATE TABLE IF NOT EXISTS cohortpeople ON CLUSTER 'posthog'
(
    person_id UUID,
    cohort_id Int64,
    team_id Int64,
    sign Int8,
    version UInt64
) ENGINE = ReplicatedCollapsingMergeTree('/clickhouse/tables/noshard/posthog.cohortpeople', '{replica}-{shard}', sign)
Order By (team_id, cohort_id, person_id, version)
