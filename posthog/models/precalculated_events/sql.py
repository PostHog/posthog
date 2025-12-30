from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.settings import CLICKHOUSE_CLUSTER

PRECALCULATED_EVENTS_TABLE = "precalculated_events"
PRECALCULATED_EVENTS_WRITABLE_TABLE = f"writable_{PRECALCULATED_EVENTS_TABLE}"
PRECALCULATED_EVENTS_SHARDED_TABLE = f"sharded_{PRECALCULATED_EVENTS_TABLE}"
PRECALCULATED_EVENTS_KAFKA_TABLE = f"kafka_{PRECALCULATED_EVENTS_TABLE}"
PRECALCULATED_EVENTS_MV = f"{PRECALCULATED_EVENTS_TABLE}_mv"


def DROP_PRECALCULATED_EVENTS_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_SHARDED_TABLE} SYNC"


def DROP_PRECALCULATED_EVENTS_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_WRITABLE_TABLE}"


def DROP_PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_TABLE}"


def DROP_PRECALCULATED_EVENTS_MV_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_MV}"


def DROP_PRECALCULATED_EVENTS_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_KAFKA_TABLE}"


def PRECALCULATED_EVENTS_SHARDED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    date Date,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = {engine}
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, condition, date, distinct_id, uuid)
""".format(
        table_name=PRECALCULATED_EVENTS_SHARDED_TABLE,
        engine=ReplacingMergeTree(
            PRECALCULATED_EVENTS_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED, ver="_timestamp"
        ),
    )


def PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL(table_name: str = PRECALCULATED_EVENTS_TABLE):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    date Date,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = {engine}
""".format(
        table_name=table_name,
        engine=Distributed(
            data_table=PRECALCULATED_EVENTS_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def PRECALCULATED_EVENTS_WRITABLE_TABLE_SQL():
    return PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL(table_name=PRECALCULATED_EVENTS_WRITABLE_TABLE)


def KAFKA_PRECALCULATED_EVENTS_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALCULATED_EVENTS_KAFKA_TABLE,
        engine=kafka_engine(topic="clickhouse_prefiltered_events", group="clickhouse_prefiltered_events"),
    )


def PRECALCULATED_EVENTS_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    toDate(_timestamp) AS date,
    distinct_id,
    person_id,
    condition,
    uuid,
    source,
    _timestamp,
    _offset,
    _partition
FROM {kafka_table_name}
    """.format(
        mv_name=PRECALCULATED_EVENTS_MV,
        writable_table_name=PRECALCULATED_EVENTS_WRITABLE_TABLE,
        kafka_table_name=PRECALCULATED_EVENTS_KAFKA_TABLE,
    )
