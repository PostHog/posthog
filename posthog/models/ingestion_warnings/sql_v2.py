from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_INGESTION_WARNINGS_V2, kafka_engine
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_INGESTION_WARNINGS

# Ingestion warnings v2: additive, structured warnings table living on the aux cluster
# (single shard, replicated). It reads the same `clickhouse_ingestion_warnings` Kafka topic
# as v1 through a dedicated consumer group, so it receives the full stream independently
# without touching the legacy path.
#
# Structured dimensions (category, severity, pipeline_step) and entity ids are DEFAULT
# expressions parsing the `details` JSON, so agents/MCP can filter without re-parsing JSON
# at query time. DEFAULT rather than MATERIALIZED: the MV (or producers) can later set the
# columns explicitly without a schema change, which MATERIALIZED would forbid.

TABLE_NAME = "ingestion_warnings_v2"
KAFKA_TABLE_NAME = f"kafka_{TABLE_NAME}"
MV_NAME = f"{TABLE_NAME}_mv"
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"

# Storage columns for the data + distributed tables. Derived dimensions and entity ids have
# DEFAULT expressions over the raw `details` JSON; the JSON key names must match what the
# producers emit (a mismatch just yields the default/NULL, it does not break ingestion).
INGESTION_WARNINGS_V2_COLUMNS = """
    team_id Int64,
    source LowCardinality(String),
    type LowCardinality(String),
    details String,
    timestamp DateTime64(6, 'UTC'),
    category LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'category'), ''), 'unknown'),
    severity LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'severity'), ''), 'warning'),
    pipeline_step LowCardinality(String) DEFAULT coalesce(nullIf(JSONExtractString(details, 'pipelineStep'), ''), 'unknown'),
    event_uuid Nullable(UUID) DEFAULT toUUIDOrNull(JSONExtractString(details, 'eventUuid')),
    distinct_id Nullable(String) DEFAULT nullIf(JSONExtractString(details, 'distinctId'), ''),
    group_key Nullable(String) DEFAULT nullIf(JSONExtractString(details, 'groupKey'), ''),
    person_id Nullable(UUID) DEFAULT toUUIDOrNull(JSONExtractString(details, 'personId')),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
"""

# Kafka engine table mirrors the current producer message shape only (team_id, source, type,
# details, timestamp). New dimensions are derived from `details` in the MV, so no producer or
# topic-schema change is required to start populating v2.
KAFKA_INGESTION_WARNINGS_V2_COLUMNS = """
    team_id Int64,
    source LowCardinality(String),
    type String,
    details String,
    timestamp DateTime64(6, 'UTC')
"""


def INGESTION_WARNINGS_V2_DATA_TABLE_SQL() -> str:
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
) ENGINE = {engine}
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, type, timestamp)
TTL toDateTime(timestamp) + INTERVAL 90 DAY
""".format(
        table_name=TABLE_NAME,
        columns=INGESTION_WARNINGS_V2_COLUMNS,
        engine=MergeTreeEngine(TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
    )


def KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL() -> str:
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
) ENGINE = {engine}
""".format(
        table_name=KAFKA_TABLE_NAME,
        columns=KAFKA_INGESTION_WARNINGS_V2_COLUMNS,
        engine=kafka_engine(
            topic=KAFKA_INGESTION_WARNINGS,
            group=CONSUMER_GROUP_INGESTION_WARNINGS_V2,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
    )


def INGESTION_WARNINGS_V2_MV_SQL() -> str:
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name}
TO {database}.{target_table}
AS SELECT
    team_id,
    source,
    type,
    details,
    timestamp,
    _timestamp,
    _offset,
    _partition
FROM {database}.{kafka_table}
""".format(
        mv_name=MV_NAME,
        target_table=TABLE_NAME,
        kafka_table=KAFKA_TABLE_NAME,
        database=settings.CLICKHOUSE_DATABASE,
    )


def DISTRIBUTED_INGESTION_WARNINGS_V2_TABLE_SQL() -> str:
    return """
CREATE TABLE IF NOT EXISTS {table_name}
(
    {columns}
) ENGINE = {engine}
""".format(
        table_name=DISTRIBUTED_TABLE_NAME,
        columns=INGESTION_WARNINGS_V2_COLUMNS,
        engine=Distributed(data_table=TABLE_NAME, cluster=settings.CLICKHOUSE_AUX_CLUSTER),
    )


DROP_INGESTION_WARNINGS_V2_MV_SQL = f"DROP TABLE IF EXISTS {MV_NAME}"
DROP_KAFKA_INGESTION_WARNINGS_V2_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_TABLE_NAME}"
DROP_DISTRIBUTED_INGESTION_WARNINGS_V2_TABLE_SQL = f"DROP TABLE IF EXISTS {DISTRIBUTED_TABLE_NAME}"
DROP_INGESTION_WARNINGS_V2_DATA_TABLE_SQL = f"DROP TABLE IF EXISTS {TABLE_NAME} SYNC"
