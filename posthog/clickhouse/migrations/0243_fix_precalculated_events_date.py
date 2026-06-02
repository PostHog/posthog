from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_events.sql import (
    KAFKA_PRECALCULATED_EVENTS_TABLE_SQL,
    KAFKA_PRECALCULATED_EVENTS_WS_TABLE_SQL,
    PRECALCULATED_EVENTS_KAFKA_TABLE,
    PRECALCULATED_EVENTS_MV,
    PRECALCULATED_EVENTS_MV_SQL,
    PRECALCULATED_EVENTS_WS_KAFKA_TABLE,
    PRECALCULATED_EVENTS_WS_MV,
    PRECALCULATED_EVENTS_WS_MV_SQL,
)

# The precalculated_events materialized view was deriving `date` from `toDate(_timestamp)`,
# where `_timestamp` is the Kafka ingestion time. That broke backfills: events inserted by the
# temporal backfill workflow always ended up with `date = today`, regardless of the event's
# actual date.
#
# Fix: add a Nullable(Date) `date` column to the Kafka engine tables so the producer's `date`
# field is read, and update the MVs to prefer the incoming date, falling back to
# `toDate(_timestamp)` when absent (realtime path still works unchanged).
#
# The sharded target table is unchanged; only the Kafka engine tables and MVs are recreated.
#
# CLOUD-ONLY (WS): non-cloud environments (CI, dev, hobby) have a single ClickHouse node where
# both the MSK and WS materialized views consume the same Kafka topic and write to the same
# target, causing double-ingest. WS objects are only recreated in cloud; in non-cloud they are
# dropped (if present) and not recreated.

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # Drop MVs first so the Kafka tables can be recreated without a brief double-write window.
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_MV}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_WS_MV}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_KAFKA_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_WS_KAFKA_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    # Recreate MSK objects on all environments.
    run_sql_with_exceptions(
        KAFKA_PRECALCULATED_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        PRECALCULATED_EVENTS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
] + (
    [
        # WarpStream path is cloud-only: recreating it in non-cloud double-ingests because
        # the warpstream_calculated_events named collection points at the same Kafka hosts.
        run_sql_with_exceptions(
            KAFKA_PRECALCULATED_EVENTS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            PRECALCULATED_EVENTS_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
    if _is_cloud
    else []
)
