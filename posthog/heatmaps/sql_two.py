from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_HEATMAP_EVENTS

HEATMAPS_DATA_TABLE = lambda: "sharded_heatmaps"

# using JSONAsString we can send multiple JSON items in a single kafka messages,
# but we have to write to a String column
# JSONEachRow checks that the payload it is receiving starts with '{'
KAFKA_HEATMAPS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    kafka_payload String
) ENGINE = {engine}
"""

KAFKA_HEATMAPS_TWO_TABLE_SQL = lambda: KAFKA_HEATMAPS_TABLE_BASE_SQL.format(
    table_name="kafka_heatmaps_two",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_HEATMAP_EVENTS, serialization="JSONAsString"),
)

# now the materialized view that ingests from it "simply" extracts values from that json payload
HEATMAPS_TABLE_TWO_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS heatmaps_two_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
    JSONExtractString(kafka_payload, 'session_id') as session_id,
    JSONExtractInt(kafka_payload, 'team_id') as team_id,
    JSONExtractString(kafka_payload, 'distinct_id') as distinct_id,
    toDateTime64(JSONExtractString(kafka_payload, 'timestamp'), 6, 'UTC') AS timestamp,
    JSONExtractInt(kafka_payload, 'x') AS x,
    JSONExtractInt(kafka_payload, 'y') AS y,
    JSONExtractInt(kafka_payload, 'scale_factor') AS scale_factor,
    JSONExtractInt(kafka_payload, 'viewport_width') AS viewport_width,
    JSONExtractInt(kafka_payload, 'viewport_height') AS viewport_height,
    JSONExtractBool(kafka_payload, 'pointer_target_fixed') AS pointer_target_fixed,
    JSONExtractString(kafka_payload, 'current_url') AS current_url,
    JSONExtractString(kafka_payload, 'type') AS type,
    _timestamp,
    _offset,
    _partition
FROM {database}.kafka_heatmaps_two
""".format(
        target_table="writable_heatmaps",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
)
