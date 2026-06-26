from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_person_properties.condition_watermark_sql import (
    KAFKA_PRECALC_CONDITION_WATERMARK_TABLE_SQL,
    KAFKA_PRECALC_CONDITION_WATERMARK_WS_TABLE_SQL,
    PRECALC_CONDITION_WATERMARK_DISTRIBUTED_TABLE_SQL,
    PRECALC_CONDITION_WATERMARK_MV_SQL,
    PRECALC_CONDITION_WATERMARK_SHARDED_TABLE_SQL,
    PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE_SQL,
    PRECALC_CONDITION_WATERMARK_WS_MV_SQL,
)

# Compact "last write time per (team, condition)" watermark over the precalculated person-properties
# write stream. Both MSK and WarpStream Kafka tables consume the existing
# `clickhouse_precalculated_person_properties` topic via dedicated consumer groups (independent of
# the precalc ingestion consumers) and feed a single sharded ReplacingMergeTree via the writable
# distributed table. See condition_watermark_sql.py for the rationale.

operations = [
    run_sql_with_exceptions(PRECALC_CONDITION_WATERMARK_SHARDED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PRECALC_CONDITION_WATERMARK_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PRECALC_CONDITION_WATERMARK_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(KAFKA_PRECALC_CONDITION_WATERMARK_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALC_CONDITION_WATERMARK_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(KAFKA_PRECALC_CONDITION_WATERMARK_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
    run_sql_with_exceptions(PRECALC_CONDITION_WATERMARK_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_MEDIUM]),
]
