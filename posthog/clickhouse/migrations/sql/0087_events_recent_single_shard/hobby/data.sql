DROP TABLE IF EXISTS distributed_events_recent ON CLUSTER 'posthog'

CREATE TABLE IF NOT EXISTS distributed_events_recent 
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties VARCHAR Codec(ZSTD(3)),
    group0_properties VARCHAR Codec(ZSTD(3)),
    group1_properties VARCHAR Codec(ZSTD(3)),
    group2_properties VARCHAR Codec(ZSTD(3)),
    group3_properties VARCHAR Codec(ZSTD(3)),
    group4_properties VARCHAR Codec(ZSTD(3)),
    group0_created_at DateTime64,
    group1_created_at DateTime64,
    group2_created_at DateTime64,
    group3_created_at DateTime64,
    group4_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    historical_migration Bool
    
    
    
, _timestamp DateTime
, _offset UInt64
, inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NOW64()
    
) ENGINE = Distributed('posthog_primary_replica', 'default', 'sharded_events_recent', sipHash64(distinct_id))
