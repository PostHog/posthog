from posthog.clickhouse.kafka_engine import kafka_engine, ttl_period
from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.settings.data_stores import CLICKHOUSE_SINGLE_SHARD_CLUSTER

# Behavioral cohorts matches table

BEHAVIORAL_COHORTS_MATCHES_TABLE = "behavioral_cohorts_matches"
BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE = f"writable_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE = f"sharded_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE = f"kafka_{BEHAVIORAL_COHORTS_MATCHES_TABLE}"
BEHAVIORAL_COHORTS_MATCHES_MV = f"{BEHAVIORAL_COHORTS_MATCHES_TABLE}_mv"
BEHAVIORAL_COHORTS_MATCHES_TTL_DAYS = 30


def DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE} SYNC"


def DROP_BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE}"


def DROP_BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_TABLE}"


def DROP_BEHAVIORAL_COHORTS_MATCHES_MV_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_MV}"


def DROP_BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {BEHAVIORAL_COHORTS_MATCHES_KAFKA_TABLE}"


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


# Cohort membership table, that stores the membership for each cohort and condition for each date.

COHORT_MEMBERSHIP_TABLE = "cohort_membership"
COHORT_MEMBERSHIP_WRITABLE_TABLE = f"writable_{COHORT_MEMBERSHIP_TABLE}"
COHORT_MEMBERSHIP_KAFKA_TABLE = f"kafka_{COHORT_MEMBERSHIP_TABLE}"
COHORT_MEMBERSHIP_MV = f"{COHORT_MEMBERSHIP_TABLE}_mv"
COHORT_MEMBERSHIP_TTL_DAYS = 30


def COHORT_MEMBERSHIP_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6) DEFAULT now64()
) ENGINE = {engine}
ORDER BY (team_id, cohort_id, person_id)
""".format(table_name=COHORT_MEMBERSHIP_TABLE, engine=ReplacingMergeTree(COHORT_MEMBERSHIP_TABLE, ver="last_updated"))


def COHORT_MEMBERSHIP_WRITABLE_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6) DEFAULT now64()
) ENGINE = {engine}
""".format(
        table_name=COHORT_MEMBERSHIP_WRITABLE_TABLE,
        engine=Distributed(COHORT_MEMBERSHIP_TABLE, cluster=CLICKHOUSE_SINGLE_SHARD_CLUSTER),
    )


def KAFKA_COHORT_MEMBERSHIP_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6)
) ENGINE = {engine}
""".format(
        table_name=COHORT_MEMBERSHIP_KAFKA_TABLE,
        engine=kafka_engine(topic="cohort_membership_changed", group="clickhouse_cohort_membership"),
    )


def COHORT_MEMBERSHIP_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    cohort_id,
    person_id,
    status,
    last_updated
FROM {kafka_table_name}
""".format(
        mv_name=COHORT_MEMBERSHIP_MV,
        writable_table_name=COHORT_MEMBERSHIP_WRITABLE_TABLE,
        kafka_table_name=COHORT_MEMBERSHIP_KAFKA_TABLE,
    )


# Prefiltered events table
PREFILTERED_EVENTS_TABLE = "prefiltered_events"
PREFILTERED_EVENTS_SHARDED_TABLE = f"sharded_{PREFILTERED_EVENTS_TABLE}"
PREFILTERED_EVENTS_WRITABLE_TABLE = "writable_prefiltered_events"
PREFILTERED_EVENTS_KAFKA_TABLE = "kafka_prefiltered_events"
PREFILTERED_EVENTS_MV = "prefiltered_events_mv"


def PREFILTERED_EVENTS_TABLE_SQL():
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
ORDER BY (team_id, condition, date, distinct_id, uuid)
PARTITION BY toYYYYMM(date)
""".format(
        table_name=PREFILTERED_EVENTS_SHARDED_TABLE,
        engine=ReplacingMergeTree(ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED),
    )


def PREFILTERED_EVENTS_DISTRIBUTED_TABLE_SQL(table_name: str = PREFILTERED_EVENTS_TABLE):
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
        engine=Distributed(PREFILTERED_EVENTS_SHARDED_TABLE, sharding_key="sipHash64(distinct_id)"),
    )


def PREFILTERED_EVENTS_WRITABLE_TABLE_SQL():
    return PREFILTERED_EVENTS_DISTRIBUTED_TABLE_SQL(table_name=PREFILTERED_EVENTS_WRITABLE_TABLE)


def KAFKA_PREFILTERED_EVENTS_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    evaluation_timestamp DateTime64(6),
    distinct_id String,
    person_id UUID,
    condition String,
    uuid UUID,
    source String
) ENGINE = {engine}
""".format(
        table_name=PREFILTERED_EVENTS_KAFKA_TABLE,
        engine=kafka_engine(topic="clickhouse_prefiltered_events", group="clickhouse_prefiltered_events"),
    )


def PREFILTERED_EVENTS_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    toDate(evaluation_timestamp) AS date,
    distinct_id,
    person_id,
    condition,
    uuid,
    source,
    _timestamp,
    _partition,
    _offset
FROM {kafka_table_name}
""".format(
        mv_name=PREFILTERED_EVENTS_MV,
        writable_table_name=PREFILTERED_EVENTS_WRITABLE_TABLE,
        kafka_table_name=PREFILTERED_EVENTS_KAFKA_TABLE,
    )
