from django.conf import settings

from ee.clickhouse.sql.clickhouse import KAFKA_COLUMNS, kafka_engine, ttl_period
from ee.clickhouse.sql.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from ee.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION

LIVE_EVENTS_DATA_TABLE = "sharded_live_events"

LIVE_EVENTS_DATA_TABLE_ENGINE = lambda: ReplacingMergeTree(
    "live_events", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
)

LIVE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC')
    {extra_fields}
) ENGINE = {engine}
"""

LIVE_EVENTS_TABLE_SQL = lambda: (
    LIVE_EVENTS_TABLE_BASE_SQL
    + """
    PARTITION BY toStartOfTenMinutes(_timestamp)
    ORDER BY (team_id, timestamp, event, cityHash64(distinct_id), cityHash64(uuid))
    {settings}
    {ttl_period}
    """
).format(
    table_name=LIVE_EVENTS_DATA_TABLE,
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=LIVE_EVENTS_DATA_TABLE_ENGINE(),
    extra_fields=KAFKA_COLUMNS,
    settings="SETTINGS merge_with_ttl_timeout=3600",
    ttl_period=ttl_period("_timestamp", "10 MINUTE"),
)

KAFKA_LIVE_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    uuid UUID,
    data VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    sent_at VARCHAR
) ENGINE = {engine}
{settings}
"""

KAFKA_LIVE_EVENTS_TABLE_SQL = lambda: KAFKA_LIVE_EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_live_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(
        topic=KAFKA_EVENTS_PLUGIN_INGESTION, group="clickhouse-live-events-1"
    ),  # being very specific with the group name to avoid clashes
    settings="SETTINGS kafka_max_block_size=65505, kafka_skip_broken_messages=65505",
)

LIVE_EVENTS_TABLE_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW live_events_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
uuid,
JSONExtractString(data, 'event') as event,
JSONExtractRaw(data, 'properties') as properties,
parseDateTime64BestEffortOrNull(sent_at) as timestamp,
team_id,
distinct_id,
'' as elements_chain,
now() as created_at,
_timestamp,
_offset
FROM {database}.kafka_live_events
""".format(
    target_table="writable_live_events", cluster=settings.CLICKHOUSE_CLUSTER, database=settings.CLICKHOUSE_DATABASE,
)

WRITABLE_LIVE_EVENTS_TABLE_SQL = lambda: LIVE_EVENTS_TABLE_BASE_SQL.format(
    table_name="writable_live_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=LIVE_EVENTS_DATA_TABLE, sharding_key="sipHash64(distinct_id)"),
    extra_fields=KAFKA_COLUMNS,
)

DISTRIBUTED_LIVE_EVENTS_TABLE_SQL = lambda: LIVE_EVENTS_TABLE_BASE_SQL.format(
    table_name="live_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=LIVE_EVENTS_DATA_TABLE, sharding_key="sipHash64(distinct_id)"),
    extra_fields=KAFKA_COLUMNS,
)
