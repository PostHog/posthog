from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.models.precalculated_events.sql import PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL
from posthog.models.precalculated_person_properties.sql import (
    PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE,
    PRECALCULATED_PERSON_PROPERTIES_MV,
    PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE,
    PRECALCULATED_PERSON_PROPERTIES_TABLE,
    PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE,
)
from posthog.settings import CLICKHOUSE_CLUSTER


# Original schema without person_id - frozen for this migration
def PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL_V1():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = {engine}
ORDER BY (team_id, condition, distinct_id)
""".format(
        table_name=PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE,
        engine=ReplacingMergeTree(
            PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE,
            replication_scheme=ReplicationScheme.SHARDED,
            ver="_timestamp",
        ),
    )


def PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL_V1(
    table_name: str = PRECALCULATED_PERSON_PROPERTIES_TABLE,
):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = {engine}
""".format(
        table_name=table_name,
        engine=Distributed(
            data_table=PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL_V1():
    return PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL_V1(
        table_name=PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE
    )


def KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL_V1():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    distinct_id String,
    condition String,
    matches Bool,
    source String
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE,
        engine=kafka_engine(
            topic="clickhouse_precalculated_person_properties", group="clickhouse_precalculated_person_properties"
        ),
    )


def PRECALCULATED_PERSON_PROPERTIES_MV_SQL_V1():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    distinct_id,
    condition,
    matches,
    source,
    _timestamp,
    _offset
FROM {kafka_table_name}
    """.format(
        mv_name=PRECALCULATED_PERSON_PROPERTIES_MV,
        writable_table_name=PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE,
        kafka_table_name=PRECALCULATED_PERSON_PROPERTIES_KAFKA_TABLE,
    )


operations = [
    # Add precalculated_events distributed table to COORDINATOR nodes (already exists on DATA from 0175)
    run_sql_with_exceptions(PRECALCULATED_EVENTS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.COORDINATOR]),
    # Create precalculated_person_properties tables with distinct_id (without person_id)
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_SHARDED_TABLE_SQL_V1(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_DISTRIBUTED_TABLE_SQL_V1(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        KAFKA_PRECALCULATED_PERSON_PROPERTIES_TABLE_SQL_V1(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(
        PRECALCULATED_PERSON_PROPERTIES_WRITABLE_TABLE_SQL_V1(), node_roles=[NodeRole.INGESTION_MEDIUM]
    ),
    run_sql_with_exceptions(PRECALCULATED_PERSON_PROPERTIES_MV_SQL_V1(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
