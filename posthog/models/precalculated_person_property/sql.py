from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.settings import CLICKHOUSE_CLUSTER

PRECALCULATED_PERSON_PROPERTY_TABLE = "precalculated_person_property"
PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE = f"writable_{PRECALCULATED_PERSON_PROPERTY_TABLE}"
PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE = f"sharded_{PRECALCULATED_PERSON_PROPERTY_TABLE}"
PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE = f"kafka_{PRECALCULATED_PERSON_PROPERTY_TABLE}"
PRECALCULATED_PERSON_PROPERTY_MV = f"{PRECALCULATED_PERSON_PROPERTY_TABLE}_mv"


def DROP_PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE} SYNC"


def DROP_PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE}"


def DROP_PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_PERSON_PROPERTY_TABLE}"


def DROP_PRECALCULATED_PERSON_PROPERTY_MV_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_PERSON_PROPERTY_MV}"


def DROP_PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE}"


def PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    date Date,
    person_id UUID,
    condition String,
    matches Int8,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = {engine}
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, condition, person_id)
""".format(
        table_name=PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE,
        engine=ReplacingMergeTree(
            PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED, ver="_timestamp"
        ),
    )


def PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL(table_name: str = PRECALCULATED_PERSON_PROPERTY_TABLE):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    date Date,
    person_id UUID,
    condition String,
    matches Int8,
    source String,
    _timestamp DateTime64(6),
    _partition UInt64,
    _offset UInt64
) ENGINE = {engine}
""".format(
        table_name=table_name,
        engine=Distributed(
            data_table=PRECALCULATED_PERSON_PROPERTY_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(person_id)",
        ),
    )


def PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE_SQL():
    return PRECALCULATED_PERSON_PROPERTY_DISTRIBUTED_TABLE_SQL(table_name=PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE)


def KAFKA_PRECALCULATED_PERSON_PROPERTY_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    evaluation_timestamp DateTime64(6),
    person_id UUID,
    condition String,
    matches Int8,
    source String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE,
        engine=kafka_engine(
            topic="clickhouse_prefiltered_person_properties", group="clickhouse_prefiltered_person_properties"
        ),
    )


def PRECALCULATED_PERSON_PROPERTY_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    toDate(evaluation_timestamp) AS date,
    person_id,
    condition,
    matches,
    source,
    _timestamp,
    _offset,
    _partition
FROM {kafka_table_name}
    """.format(
        mv_name=PRECALCULATED_PERSON_PROPERTY_MV,
        writable_table_name=PRECALCULATED_PERSON_PROPERTY_WRITABLE_TABLE,
        kafka_table_name=PRECALCULATED_PERSON_PROPERTY_KAFKA_TABLE,
    )
