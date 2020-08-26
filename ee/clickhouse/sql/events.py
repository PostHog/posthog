EVENT_SQL = """
CREATE TABLE events
(
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime,
    team_id Int32,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp, intHash32(team_id))
SAMPLE BY intHash32(team_id)
"""
