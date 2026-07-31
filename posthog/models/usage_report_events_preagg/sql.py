from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG, kafka_engine
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

USAGE_REPORT_EVENTS_PREAGG_TABLE = "usage_report_events_preagg"
SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"sharded_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"
WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"writable_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"
USAGE_REPORT_EVENTS_PREAGG_MV = f"{USAGE_REPORT_EVENTS_PREAGG_TABLE}_mv"

# Dedicated Kafka engine table. We do NOT reuse `kafka_events_json_ws` (the
# main events ingestion path) — every MV attached to a Kafka engine table
# shares its consumer offsets, so a slow or broken aggregate MV would
# back-pressure the main events pipeline. Own consumer group, own failure domain.
KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE = f"kafka_{USAGE_REPORT_EVENTS_PREAGG_TABLE}"

USAGE_REPORT_EVENTS_PREAGG_TTL_DAYS = 14


USAGE_REPORT_EVENTS_PREAGG_COLUMNS = """
    date Date,
    team_id Int64,
    person_mode LowCardinality(String),
    lib LowCardinality(String),
    event String,
    distinct_events_unique AggregateFunction(uniqExact, Tuple(UInt64, UInt64, UInt64)),
    event_count AggregateFunction(sum, UInt64)
""".strip()


# Slim Kafka engine table schema — only the columns the MV projects.
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
ENGINE = {
        Distributed(
            data_table=SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
            sharding_key="sipHash64(date)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        Distributed(
            data_table=SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
            sharding_key="sipHash64(date)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        )
    }
"""


def KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}
(
    {_KAFKA_USAGE_REPORT_EVENTS_PREAGG_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_EVENTS_JSON,
            group=CONSUMER_GROUP_USAGE_REPORT_EVENTS_PREAGG,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_num_consumers = 1
"""


def USAGE_REPORT_EVENTS_PREAGG_MV_SQL() -> str:
    # Dedup tuple includes `event` (avoids cross-event uuid collisions) but not `date`
    # (so day-boundary replays still dedupe).
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {USAGE_REPORT_EVENTS_PREAGG_MV}
TO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
AS SELECT
    toDate(timestamp) AS date,
    team_id,
    person_mode,
    JSONExtractString(properties, '$lib') AS lib,
    event,
    uniqExactState((cityHash64(distinct_id), cityHash64(toString(uuid)), cityHash64(event))) AS distinct_events_unique,
    sumState(toUInt64(1)) AS event_count
FROM {KAFKA_USAGE_REPORT_EVENTS_PREAGG_TABLE}
GROUP BY date, team_id, person_mode, lib, event
"""
