from infi.clickhouse_orm import migrations

EVENT_SQL = """
CREATE TABLE default.events
(
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    element VARCHAR,
    timestamp DateTime,
    team_id Int32,
    distinct_id UUID,
    elements_hash VARCHAR,
    created_at DateTime
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp, intHash32(team_id))
SAMPLE BY intHash32(team_id)
"""

operations = [
    migrations.RunSQL(EVENT_SQL),
]
