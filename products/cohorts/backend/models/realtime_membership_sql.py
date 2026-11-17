from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP, kafka_engine, kafka_num_consumers
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree
from posthog.kafka_client.topics import KAFKA_COHORT_MEMBERSHIP_CHANGED

REALTIME_COHORT_MEMBERSHIP_TABLE = "realtime_cohort_membership"
WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE = f"writable_{REALTIME_COHORT_MEMBERSHIP_TABLE}"
KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE = f"kafka_{REALTIME_COHORT_MEMBERSHIP_TABLE}"
REALTIME_COHORT_MEMBERSHIP_MV = f"{REALTIME_COHORT_MEMBERSHIP_TABLE}_mv"

# A member row is a membership change: in_cohort is 1 for entered and 0 for left, and version is its last_updated.
# A floor row is one partition's copy of a sweep floor: floor_partition is the topic partition of the copy,
# floor_partitions is the number of copies that complete the floor, and version is its threshold.
# The columns that do not apply to a kind hold zero. Reconcile changes carry a run_id, so a member row that kept it
# in floor_run_id would give one person a second sorting key.
REALTIME_COHORT_MEMBERSHIP_COLUMNS = """
    team_id Int64,
    cohort_id Int64,
    kind Enum8('member' = 0, 'floor' = 1),
    person_id UUID,
    floor_run_id UUID,
    floor_partition UInt16,
    in_cohort UInt8,
    version DateTime64(6, 'UTC'),
    floor_partitions UInt16
""".strip()

# The text fields are String so that a bad value reaches the view, which drops the row. In a typed column, a bad value
# fails the parse and counts against kafka_skip_broken_messages.
KAFKA_REALTIME_COHORT_MEMBERSHIP_COLUMNS = """
    type String,
    team_id Int64,
    cohort_id Int64,
    person_id String,
    status String,
    last_updated String,
    run_id String,
    threshold String,
    partitions UInt16
""".strip()

ZERO_UUID_EXPR = "toUUID('00000000-0000-0000-0000-000000000000')"


def REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    # No TTL: when a left row or a floor row expires, the older rows it hides count again.
    return f"""
CREATE TABLE IF NOT EXISTS {REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {REALTIME_COHORT_MEMBERSHIP_COLUMNS}
)
ENGINE = {ReplacingMergeTree(REALTIME_COHORT_MEMBERSHIP_TABLE, ver="version")}
ORDER BY (team_id, cohort_id, kind, person_id, floor_run_id, floor_partition)
"""


def WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {REALTIME_COHORT_MEMBERSHIP_COLUMNS}
)
ENGINE = {Distributed(data_table=REALTIME_COHORT_MEMBERSHIP_TABLE, cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)}
"""


def KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE}
(
    {KAFKA_REALTIME_COHORT_MEMBERSHIP_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_COHORT_MEMBERSHIP_CHANGED,
            group=CONSUMER_GROUP_REALTIME_COHORT_MEMBERSHIP,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        )
    }
SETTINGS
    kafka_skip_broken_messages = 100,
    kafka_num_consumers = {kafka_num_consumers(1)},
    kafka_thread_per_consumer = 1,
    kafka_poll_timeout_ms = 10000,
    kafka_flush_interval_ms = 7500,
    kafka_max_block_size = 100000
"""


def REALTIME_COHORT_MEMBERSHIP_MV_SELECT_SQL(source_table: str) -> str:
    # A view expression that throws stalls the consumer for good, so every conversion returns NULL on bad input and the
    # outer WHERE drops those rows. The inner select gives converted values new names, because an output alias named
    # like a source column shadows that column in WHERE.
    # toDateTime64OrNull also accepts what the producers never write: an empty string reads as the epoch and February 30
    # rolls over to March 2. So a stamp must print back to the text it came from.
    # A record of any other type is dropped, so a new kind of control record needs no change here.
    return f"""SELECT
    team_id,
    cohort_id,
    if(is_floor, 'floor', 'member') AS kind,
    if(is_floor, {ZERO_UUID_EXPR}, ifNull(person_uuid, {ZERO_UUID_EXPR})) AS person_id,
    if(is_floor, ifNull(run_uuid, {ZERO_UUID_EXPR}), {ZERO_UUID_EXPR}) AS floor_run_id,
    if(is_floor, toUInt16(_partition), 0) AS floor_partition,
    toUInt8(status = 'entered') AS in_cohort,
    assumeNotNull(stamp) AS version,
    if(is_floor, partitions, 0) AS floor_partitions
FROM (
    SELECT
        team_id,
        cohort_id,
        type = 'sweep_floor' AS is_floor,
        toUUIDOrNull(person_id) AS person_uuid,
        toUUIDOrNull(run_id) AS run_uuid,
        if(is_floor, threshold, last_updated) AS raw_stamp,
        toDateTime64OrNull(raw_stamp, 6, 'UTC') AS stamp,
        status,
        partitions,
        _partition
    FROM {source_table}
    WHERE type IN ('', 'sweep_floor')
)
WHERE toString(stamp) = raw_stamp
  AND if(is_floor, run_uuid IS NOT NULL AND partitions > 0, person_uuid IS NOT NULL AND status IN ('entered', 'left'))"""


def REALTIME_COHORT_MEMBERSHIP_MV_SQL() -> str:
    return f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {REALTIME_COHORT_MEMBERSHIP_MV}
TO {WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE}
AS {REALTIME_COHORT_MEMBERSHIP_MV_SELECT_SQL(KAFKA_REALTIME_COHORT_MEMBERSHIP_TABLE)}
"""


TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {REALTIME_COHORT_MEMBERSHIP_TABLE}"
