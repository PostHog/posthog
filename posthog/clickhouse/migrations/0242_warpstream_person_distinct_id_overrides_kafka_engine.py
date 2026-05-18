from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES_WS_TABLE_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_WS_MV_SQL,
)

# Migration to create a WarpStream Kafka engine table for person_distinct_id_overrides.
#
# These tables coexist alongside the existing MSK Kafka engine table, reading from the
# same clickhouse_person_distinct_id topic but via the warpstream_ingestion named
# collection with its own consumer group to avoid conflicts with the MSK table.
#
# The overrides MV shares the clickhouse_person_distinct_id topic with
# person_distinct_id2 (the MV filters with `WHERE version > 0`), so we need a
# dedicated consumer group for the WS path here as well.
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) there is only one ClickHouse
# node, so both the MSK and WS materialized views would consume the same Kafka topic
# and write to the same target table, doubling every person_distinct_id_overrides row.
#
# New tables (INGESTION_SMALL, matching existing MSK table from migration 0152):
# - kafka_person_distinct_id_overrides_ws + person_distinct_id_overrides_ws_mv

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        run_sql_with_exceptions(
            KAFKA_PERSON_DISTINCT_ID_OVERRIDES_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            PERSON_DISTINCT_ID_OVERRIDES_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
    ]
)
