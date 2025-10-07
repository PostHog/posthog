from posthog.clickhouse.kafka_engine import kafka_engine, ttl_period
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme
from posthog.settings import CLICKHOUSE_CLUSTER

BEHAVIORAL_COHORTS_MATCHES_TABLE = "behavioral_cohorts_matches"
BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE = f"writable_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE = f"sharded_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE = f"kafka_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_MV = f"{BEHAVIORAL_COHORTS_MATCHES_TABLE}_mv"
BEHAVIORAL_COHORTS_MATCHES_TTL_DAYS = 30


def DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE}"


def DROP_BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE}"


def DROP_BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_TABLE}"


def BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    date Date,
    person_id UUID,
    condition String,
    matches SimpleAggregateFunction(sum, UInt64),
    latest_event_is_match AggregateFunction(argMax, UInt8, DateTime64(6))
) ENGINE = {engine}
PARTITION BY toYYYYMM(date)
ORDER BY (team_id, cohort_id, condition, date, person_id)
{ttl_period}
SETTINGS ttl_only_drop_parts = 1
""".format(
        table_name=BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE,
        engine=AggregatingMergeTree(
            BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE, replication_scheme=ReplicationScheme.SHARDED
        ),
        ttl_period=ttl_period("date", BEHAVIORAL_COHORTS_MATCHES_TTL_DAYS, unit="DAY"),
    )


def BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL(table_name: str = BEHAVIORAL_COHORTS_MATCHES_TABLE):
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    date Date,
    person_id UUID,
    condition String,
    matches SimpleAggregateFunction(sum, UInt64),
    latest_event_is_match AggregateFunction(argMax, UInt8, DateTime64(6))
) ENGINE = {engine}
""".format(
        table_name=table_name,
        engine=Distributed(
            data_table=BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE,
            cluster=CLICKHOUSE_CLUSTER,
            sharding_key="sipHash64(person_id)",
        ),
    )


def BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL():
    return BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL(table_name=BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE)


def KAFKA_BEHAVIORAL_COHORTS_MATCHES_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    evaluation_timestamp DateTime64(6),
    person_id UUID,
    condition String,
    latest_event_is_match UInt8
) ENGINE = {engine}
SETTINGS kafka_max_block_size = 1000000, kafka_poll_max_batch_size = 100000, kafka_poll_timeout_ms = 1000, kafka_flush_interval_ms = 7500, kafka_skip_broken_messages = 100, kafka_num_consumers = 1
""".format(
        table_name=BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE,
        engine=kafka_engine(
            topic="clickhouse_behavioral_cohorts_matches", group="clickhouse_behavioral_cohorts_matches"
        ),
    )


def BEHAVIORAL_COHORTS_MATCHES_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    cohort_id,
    toDate(evaluation_timestamp) AS date,
    person_id,
    condition,
    sum(1) AS matches,
    argMaxState(latest_event_is_match, evaluation_timestamp) AS latest_event_is_match
FROM {kafka_table_name}
GROUP BY
    team_id,
    cohort_id,
    date,
    person_id,
    condition
    """.format(
        mv_name=BEHAVIORAL_COHORTS_MATCHES_MV,
        writable_table_name=BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE,
        kafka_table_name=BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE,
    )
