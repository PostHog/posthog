from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_HEATMAPS, kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_HEATMAP_EVENTS

KAFKA_HEATMAPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String)
) ENGINE = {engine}
"""

KAFKA_HEATMAPS_TABLE_SQL = lambda: KAFKA_HEATMAPS_TABLE_BASE_SQL.format(
    table_name="kafka_heatmaps",
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_HEATMAP_EVENTS, group=CONSUMER_GROUP_HEATMAPS),
)
