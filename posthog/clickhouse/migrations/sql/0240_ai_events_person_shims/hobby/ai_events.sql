CREATE TABLE IF NOT EXISTS person_distinct_id2 
(
    team_id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    is_deleted Int8,
    version Int64
    
) ENGINE = Distributed('posthog', 'default', 'person_distinct_id2')

CREATE TABLE IF NOT EXISTS person 
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8,
    version UInt64,
    last_seen_at Nullable(DateTime64)
    
) ENGINE = Distributed('posthog', 'default', 'person')
