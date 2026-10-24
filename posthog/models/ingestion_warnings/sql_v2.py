from django.conf import settings

from posthog.clickhouse.kafka_engine import CONSUMER_GROUP_INGESTION_WARNINGS_V2, kafka_engine
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
DISTRIBUTED_TABLE_NAME = f"{TABLE_NAME}_distributed"

KAFKA_TABLE_NAME = f"kafka_{TABLE_NAME}"

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
