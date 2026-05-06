from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG,
    CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG_WS,
    kafka_engine,
)
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

# Aggregate table names
USAGE_REPORT_EVENTS_PREAGG_TABLE = "usage_report_events_preagg"
SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"sharded_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"
WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"writable_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"
USAGE_REPORT_EVENTS_PREAGG_MV = f"{USAGE_REPORT_EVENTS_PREAGG_TABLE}_mv"
USAGE_REPORT_EVENTS_PREAGG_WS_MV = f"{USAGE_REPORT_EVENTS_PREAGG_TABLE}_ws_mv"

# Dedicated Kafka engine tables. We do NOT reuse `kafka_events_json` /
# `kafka_events_json_ws` (the main events ingestion path) — every MV attached
# to a Kafka engine table shares its consumer offsets, so a slow or broken
# aggregate MV would back-pressure the main events pipeline. By creating our
# own Kafka tables with their own consumer groups (mirroring the WarpStream
# pattern in posthog/models/event/sql.py), this aggregate has an independent
# consumer and an independent failure domain.
KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE = "kafka_usage_report_events_preagg"
KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE = "kafka_usage_report_events_preagg_ws"

USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS = 14


# Aggregate column list — shared across sharded, distributed, and writable tables.
USAGE_REPORT_EVENTS_PREAGG_COLUMNS = """
    date Date,
    team_id Int64,
    person_mode LowCardinality(String),
    lib LowCardinality(String),
    event String,
    distinct_events_unique AggregateFunction(uniqExact, Tuple(UInt64, UInt64)),
    event_count AggregateFunction(sum, UInt64)
""".strip()


# Slim Kafka engine table schema — only the columns the MV projects.
# Matches the corresponding fields in posthog/models/event/sql.py:EVENTS_TABLE_BASE_SQL.
# JSONEachRow ignores unknown fields, so the events_json topic payloads work as-is.
_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS = """
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
""".strip()


def SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {AggregatingMergeTree(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE, replication_scheme=ReplicationScheme.SHARDED)}
PARTITION BY date
ORDER BY (date, team_id, person_mode, lib, event)
TTL date + INTERVAL {USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS} DAY
SETTINGS ttl_only_drop_parts = 1
"""


def DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {Distributed(data_table=SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE, sharding_key="sipHash64(team_id)")}
"""


def WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {Distributed(data_table=SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE, sharding_key="sipHash64(team_id)")}
"""


def KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {kafka_engine(topic=KAFKA_EVENTS_JSON, group=CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG)}
SETTINGS kafka_skip_broken_messages = 100
"""


def KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE}
(
    {_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EVENTS_JSON,
            group=CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_num_consumers = 1
"""


# Read `$lib` from the JSON `properties` blob — the slim Kafka tables don't
# project it as a top-level column.
_USAGE_REPORT_EVENTS_PREAGG_MV_SELECT_TEMPLATE = """
AS SELECT
    toDate(timestamp) AS date,
    team_id,
    person_mode,
    JSONExtractString(properties, '$lib') AS lib,
    event,
    uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)))) AS distinct_events_unique,
    sumState(toUInt64(1)) AS event_count
FROM {kafka_table}
GROUP BY date, team_id, person_mode, lib, event
"""


def USAGE_REPORT_EVENTS_PREAGG_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {USAGE_REPORT_EVENTS_PREAGG_MV}
TO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
{_USAGE_REPORT_EVENTS_PREAGG_MV_SELECT_TEMPLATE.format(kafka_table=KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE)}
"""


def USAGE_REPORT_EVENTS_PREAGG_WS_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {USAGE_REPORT_EVENTS_PREAGG_WS_MV}
TO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
{_USAGE_REPORT_EVENTS_PREAGG_MV_SELECT_TEMPLATE.format(kafka_table=KAFKA_USAGE_REPORT_EVENTS_PREAGG_WS_TABLE)}
"""
