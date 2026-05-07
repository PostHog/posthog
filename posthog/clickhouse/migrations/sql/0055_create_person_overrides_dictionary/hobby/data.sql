CREATE OR REPLACE DICTIONARY default.person_distinct_id_overrides_dict ON CLUSTER posthog (
    `team_id` Int64, -- team_id could be made hierarchical to save some space.
    `distinct_id` String,
    `person_id` UUID
)
PRIMARY KEY team_id, distinct_id
-- For our own sanity, we explicitly write out the group by query.
SOURCE(CLICKHOUSE(
    query 'SELECT team_id, distinct_id, argMax(person_id, version) AS person_id FROM default.person_distinct_id_overrides GROUP BY team_id, distinct_id'
))
LAYOUT(complex_key_hashed())
-- ClickHouse will choose a time uniformly within 1 to 5 hours to reload the dictionary (update if necessary to meet SLAs).
LIFETIME(MIN 3600 MAX 18000)
