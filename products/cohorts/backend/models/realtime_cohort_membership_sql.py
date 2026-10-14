from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    kafka_num_consumers,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED

# ClickHouse copy of realtime cohort membership, fed from the same topic as the Postgres table the
# CDP consumer writes. Postgres serves point lookups; this table serves bulk reads joined with
# persons, such as workflow batch and broadcast audiences.
#
# One row per (team, cohort, person), and the latest last_updated wins. A person who leaves keeps a
# 'left' row, so readers take argMax(status, last_updated) or read with FINAL.
REALTIME_COHORT_MEMBERSHIP_TABLE = "realtime_cohort_membership"
WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE = f"writable_{REALTIME_COHORT_MEMBERSHIP_TABLE}"
KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE = f"kafka_{REALTIME_COHORT_MEMBERSHIP_TABLE}"
REALTIME_COHORT_MEMBERSHIP_MV = f"{REALTIME_COHORT_MEMBERSHIP_TABLE}_mv"

# origin is empty for live transitions, and names the backfill path ('seed', 'reconcile') otherwise.
REALTIME_COHORT_MEMBERSHIP_COLUMNS = """
    team_id Int64,
    cohort_id Int64,
    person_id UUID,
    status Enum8('entered' = 1, 'left' = 2),
    last_updated DateTime64(6, 'UTC'),
    origin LowCardinality(String)
""".strip()


def REALTIME_COHORT_MEMBERSHIP_ENGINE() -> ReplacingMergeTree:
    return ReplacingMergeTree(
        REALTIME_COHORT_MEMBERSHIP_TABLE,
        ver="last_updated",
        replication_scheme=ReplicationScheme.REPLICATED,
    )


def REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {REALTIME_COHORT_MEMBERSHIP_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {REALTIME_COHORT_MEMBERSHIP_ENGINE()}
ORDER BY (team_id, cohort_id, person_id)
"""


def WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {REALTIME_COHORT_MEMBERSHIP_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=REALTIME_COHORT_MEMBERSHIP_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)}
"""


# The cohort stream processor and the CDP consumer both use the warpstream-ingestion cluster.
def KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {REALTIME_COHORT_MEMBERSHIP_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
            group=CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100,
         kafka_num_consumers = {kafka_num_consumers(1)},
         kafka_thread_per_consumer = 1,
         kafka_poll_timeout_ms = 10000,
         kafka_max_block_size = 100000
"""


def REALTIME_COHORT_MEMBERSHIP_MV_SQL(target_table: str = WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE) -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {REALTIME_COHORT_MEMBERSHIP_MV}
TO {target_table}
AS SELECT
    team_id,
    cohort_id,
    person_id,
    status,
    last_updated,
    origin,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE}
"""


TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {REALTIME_COHORT_MEMBERSHIP_TABLE}"
