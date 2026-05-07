CREATE TABLE IF NOT EXISTS person ON CLUSTER 'posthog'
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
    
, _timestamp DateTime
, _offset UInt64

    , INDEX kafka_timestamp_minmax_person _timestamp TYPE minmax GRANULARITY 3
    
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person', '{replica}-{shard}', version)
ORDER BY (team_id, id)

CREATE TABLE IF NOT EXISTS person_distinct_id ON CLUSTER 'posthog'
(
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _sign Int8 DEFAULT 1,
    is_deleted Int8 ALIAS if(_sign==-1, 1, 0)
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedCollapsingMergeTree('/clickhouse/tables/noshard/posthog.person_distinct_id', '{replica}-{shard}', _sign)
Order By (team_id, distinct_id, person_id)

ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'
