from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.precalculated_events.sql import (
    KAFKA_PRECALCULATED_EVENTS_TABLE_SQL,
    PRECALCULATED_EVENTS_KAFKA_TABLE,
    PRECALCULATED_EVENTS_MV,
    PRECALCULATED_EVENTS_MV_SQL,
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
# The sharded target table is unchanged; only the Kafka engine table and MV are recreated.
#
# The *_ws pair is dropped and not recreated, because 0308 drops it. Installs that created the pair
# in 0229 still have it here.

operations = [
    # Drop MVs first so the Kafka tables can be recreated without a brief double-write window.
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_MV}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS precalculated_events_ws_mv",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {PRECALCULATED_EVENTS_KAFKA_TABLE}",
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS kafka_precalculated_events_ws",
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
]
