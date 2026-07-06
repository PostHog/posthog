from django.conf import settings

from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_WAREHOUSE_WEBHOOK_DELIVERY_STATUS,
    KAFKA_COLUMNS_WITH_PARTITION,
    kafka_engine,
    ttl_period,
)
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS

WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TTL_DAYS = 7

# AUX-resident, non-sharded table family (mirrors `hog_invocation_results`):
#   * `..._data` — local replicated table on AUX. The Kafka MV writes here.
#   * `kafka_...` — single Kafka engine table on AUX backed by the
#     warpstream-cyclotron named collection (same cluster the CDP node produces to).
#   * `..._mv` — MV on AUX, kafka → data table.
#   * `warehouse_webhook_delivery_status` — distributed read alias on AUX + DATA.
#
# Each row is one webhook delivery outcome emitted by the CDP node for a
# `warehouse_source_webhook` hog function. The data import pipeline reads recent
# rows per (team_id, source_id) to decide whether deliveries are persistently
# failing (e.g. a bad signing secret) and the run should fail non-retryably.
WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE = "warehouse_webhook_delivery_status"
WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE = f"{WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}_data"
KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE = f"kafka_{WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}"
WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_TABLE = f"{WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}_mv"


def DROP_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_SQL() -> str:
    return f"DROP TABLE IF EXISTS {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_TABLE}"


def DROP_KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL() -> str:
    return f"DROP TABLE IF EXISTS {KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}"


def WAREHOUSE_WEBHOOK_DELIVERY_STATUS_ENGINE() -> MergeTreeEngine:
    # Append-only event log on the AUX cluster — single shard, two replicas.
    return MergeTreeEngine(
        WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE,
        replication_scheme=ReplicationScheme.REPLICATED,
    )


# `schema_id` is empty for failures raised before per-event schema mapping
# (e.g. signature/auth checks) — those are source-level. `ok` is 1 for a 2xx
# delivery, 0 for a >=400 rejection. `reason` is a short human string derived
# from the hog function's HTTP response body (e.g. "Bad signature").
WAREHOUSE_WEBHOOK_DELIVERY_STATUS_COLUMNS = """
    team_id Int64,
    source_id String,
    schema_id String,
    http_status UInt16,
    ok UInt8,
    reason String,
    timestamp DateTime64(6, 'UTC')
""".strip()


WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE}
(
    {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_ENGINE()}
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (team_id, source_id, schema_id, timestamp)
{ttl_period("timestamp", WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TTL_DAYS, unit="DAY")}
"""
)


# Distributed read alias on AUX + DATA so both clusters' queries reach the data.
# The data import pipeline queries this bare name.
DISTRIBUTED_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}
(
    {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_COLUMNS}
    {KAFKA_COLUMNS_WITH_PARTITION}
)
ENGINE = {Distributed(data_table=WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE, cluster=settings.CLICKHOUSE_AUX_CLUSTER)}
"""
)


KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL = lambda: (
    f"""
CREATE TABLE IF NOT EXISTS {KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}
(
    {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_COLUMNS}
)
ENGINE = {
        kafka_engine(
            topic=KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS,
            group=CONSUMER_GROUP_WAREHOUSE_WEBHOOK_DELIVERY_STATUS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_CYCLOTRON_NAMED_COLLECTION,
        )
    }
SETTINGS kafka_skip_broken_messages = 100
"""
)


WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_SQL = lambda target_table=WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE: (
    f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_TABLE}
TO {target_table}
AS SELECT
    team_id,
    source_id,
    schema_id,
    http_status,
    ok,
    reason,
    timestamp,
    _timestamp,
    _offset,
    _partition
FROM {KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE}
"""
)


TRUNCATE_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL = (
    f"TRUNCATE TABLE IF EXISTS {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE}"
)


# Direct insert used by tests / any bypass-Kafka producer. Writes go to the
# local data table (the distributed read alias isn't writable).
INSERT_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_SQL = f"""
INSERT INTO {WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE} (
    team_id,
    source_id,
    schema_id,
    http_status,
    ok,
    reason,
    timestamp,
    _timestamp,
    _offset,
    _partition
)
SELECT
    %(team_id)s,
    %(source_id)s,
    %(schema_id)s,
    %(http_status)s,
    %(ok)s,
    %(reason)s,
    %(timestamp)s,
    now(),
    0,
    0
"""
