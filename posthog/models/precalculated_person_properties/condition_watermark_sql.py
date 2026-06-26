from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_PRECALC_CONDITION_WATERMARK,
    CONSUMER_GROUP_PRECALC_CONDITION_WATERMARK_WS,
    kafka_engine,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.settings import CLICKHOUSE_CLUSTER

# A compact "last write time per (team, condition)" watermark derived from the precalculated
# person-properties write stream. One row per (team_id, condition) holds the latest `_timestamp`
# any precalc row was written for that condition. It lets the realtime-cohort selection step skip
# recomputing a person-property-only cohort whose conditions saw no write since its last calculation.
#
# It taps the existing `clickhouse_precalculated_person_properties` topic via its OWN consumer
# groups (it does not touch the precalc ingestion tables), so a failure here only makes the
# watermark stale — the skip predicate then fails open and recomputes everything, never dropping a
# change. See cdp-precalculated-filters.consumer.ts for the producer (writes a row per event, so
# this is "a write happened", an over-approximation of "the property changed").

PRECALC_CONDITION_WATERMARK_TABLE = "precalc_condition_watermark"
PRECALC_CONDITION_WATERMARK_SHARDED_TABLE = f"sharded_{PRECALC_CONDITION_WATERMARK_TABLE}"
PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE = f"writable_{PRECALC_CONDITION_WATERMARK_TABLE}"
PRECALC_CONDITION_WATERMARK_KAFKA_TABLE = f"kafka_{PRECALC_CONDITION_WATERMARK_TABLE}"
PRECALC_CONDITION_WATERMARK_MV = f"{PRECALC_CONDITION_WATERMARK_TABLE}_mv"
PRECALC_CONDITION_WATERMARK_WS_KAFKA_TABLE = f"kafka_{PRECALC_CONDITION_WATERMARK_TABLE}_ws"
PRECALC_CONDITION_WATERMARK_WS_MV = f"{PRECALC_CONDITION_WATERMARK_TABLE}_ws_mv"

# Source topic — the same one the precalculated person-properties Kafka tables consume.
PRECALC_PERSON_PROPERTIES_TOPIC = "clickhouse_precalculated_person_properties"


def DROP_PRECALC_CONDITION_WATERMARK_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_SHARDED_TABLE} SYNC"


def DROP_PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE}"


def DROP_PRECALC_CONDITION_WATERMARK_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_TABLE}"


def DROP_PRECALC_CONDITION_WATERMARK_MV_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_MV}"


def DROP_PRECALC_CONDITION_WATERMARK_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_KAFKA_TABLE}"


def DROP_PRECALC_CONDITION_WATERMARK_WS_MV_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_WS_MV}"


def DROP_PRECALC_CONDITION_WATERMARK_WS_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALC_CONDITION_WATERMARK_WS_KAFKA_TABLE}"


def PRECALC_CONDITION_WATERMARK_SHARDED_TABLE_SQL():
    # ReplacingMergeTree on last_write_at collapses to one row per (team_id, condition) holding the
    # max write time. Reads still aggregate with max() to be correct between merges and across shards.
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    condition String,
    last_write_at DateTime64(6)
) ENGINE = {engine}
ORDER BY (team_id, condition)
""".format(
        table_name=PRECALC_CONDITION_WATERMARK_SHARDED_TABLE,
        engine=ReplacingMergeTree(
            PRECALC_CONDITION_WATERMARK_SHARDED_TABLE,
            replication_scheme=ReplicationScheme.SHARDED,
            ver="last_write_at",
        ),
    )


def PRECALC_CONDITION_WATERMARK_DISTRIBUTED_TABLE_SQL(table_name: str = PRECALC_CONDITION_WATERMARK_TABLE):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    condition String,
    last_write_at DateTime64(6)
) ENGINE = {engine}
""".format(
        table_name=table_name,
        engine=Distributed(
            data_table=PRECALC_CONDITION_WATERMARK_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(condition)",
        ),
    )


def PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE_SQL():
    return PRECALC_CONDITION_WATERMARK_DISTRIBUTED_TABLE_SQL(table_name=PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE)


def KAFKA_PRECALC_CONDITION_WATERMARK_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    condition String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALC_CONDITION_WATERMARK_KAFKA_TABLE,
        engine=kafka_engine(topic=PRECALC_PERSON_PROPERTIES_TOPIC, group=CONSUMER_GROUP_PRECALC_CONDITION_WATERMARK),
    )


def PRECALC_CONDITION_WATERMARK_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    condition,
    _timestamp AS last_write_at
FROM {kafka_table_name}
    """.format(
        mv_name=PRECALC_CONDITION_WATERMARK_MV,
        writable_table_name=PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE,
        kafka_table_name=PRECALC_CONDITION_WATERMARK_KAFKA_TABLE,
    )


# WarpStream Kafka engine tables (coexist alongside MSK tables, same topic, same target)


def KAFKA_PRECALC_CONDITION_WATERMARK_WS_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    condition String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALC_CONDITION_WATERMARK_WS_KAFKA_TABLE,
        engine=kafka_engine(
            topic=PRECALC_PERSON_PROPERTIES_TOPIC,
            group=CONSUMER_GROUP_PRECALC_CONDITION_WATERMARK_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CALCULATED_EVENTS_NAMED_COLLECTION,
        ),
    )


def PRECALC_CONDITION_WATERMARK_WS_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    condition,
    _timestamp AS last_write_at
FROM {kafka_table_name}
    """.format(
        mv_name=PRECALC_CONDITION_WATERMARK_WS_MV,
        writable_table_name=PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE,
        kafka_table_name=PRECALC_CONDITION_WATERMARK_WS_KAFKA_TABLE,
    )
