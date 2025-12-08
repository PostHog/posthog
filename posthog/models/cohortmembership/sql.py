from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.settings.data_stores import CLICKHOUSE_SINGLE_SHARD_CLUSTER

COHORT_MEMBERSHIP_TABLE = "cohort_membership"
COHORT_MEMBERSHIP_WRITABLE_TABLE = f"writable_{COHORT_MEMBERSHIP_TABLE}"
COHORT_MEMBERSHIP_KAFKA_TABLE = f"kafka_{COHORT_MEMBERSHIP_TABLE}"
COHORT_MEMBERSHIP_MV = f"{COHORT_MEMBERSHIP_TABLE}_mv"


def DROP_COHORT_MEMBERSHIP_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {COHORT_MEMBERSHIP_TABLE}"


def DROP_COHORT_MEMBERSHIP_WRITABLE_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {COHORT_MEMBERSHIP_WRITABLE_TABLE}"


def DROP_COHORT_MEMBERSHIP_MV_SQL():
    return f"DROP TABLE IF EXISTS {COHORT_MEMBERSHIP_MV}"


def DROP_COHORT_MEMBERSHIP_KAFKA_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {COHORT_MEMBERSHIP_KAFKA_TABLE}"


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
""".format(
        table_name=COHORT_MEMBERSHIP_TABLE,
        engine=ReplacingMergeTree(COHORT_MEMBERSHIP_TABLE, ver="last_updated"),
    )


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
        engine=Distributed(data_table=COHORT_MEMBERSHIP_TABLE, cluster=CLICKHOUSE_SINGLE_SHARD_CLUSTER),
    )


def KAFKA_COHORT_MEMBERSHIP_TABLE_SQL():
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    `team_id` Int64,
    `cohort_id` Int64,
    `person_id` UUID,
    `status` Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4),
    `last_updated` DateTime64(6)
) ENGINE = {engine}
""".format(
        table_name=COHORT_MEMBERSHIP_KAFKA_TABLE,
        engine=kafka_engine(topic="cohort_membership_changed", group="clickhouse_cohort_membership_changed"),
    )


def COHORT_MEMBERSHIP_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} TO {writable_table_name}
AS SELECT
    team_id,
    cohort_id,
    person_id,
    multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
    last_updated
FROM {kafka_table_name}
    """.format(
        mv_name=COHORT_MEMBERSHIP_MV,
        writable_table_name=COHORT_MEMBERSHIP_WRITABLE_TABLE,
        kafka_table_name=COHORT_MEMBERSHIP_KAFKA_TABLE,
    )
