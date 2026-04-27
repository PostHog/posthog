from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import ALTER_TABLE_ADD_DMAT_STRING_COLUMNS, EVENTS_DATA_TABLE

# Expand the dmat_string column pool from 10 to 100 columns to support the weekly
# batched dynamic property materialization workflow. NULL columns compress to near-zero
# (a few bytes per granule for the null bitmap), so the unused capacity is essentially
# free and gives ~19 weeks of runway at 5 columns/week before compaction is needed.
#
# Existing dmat_numeric_*, dmat_bool_*, and dmat_datetime_* columns remain in the schema
# but are no longer assigned to new slots — the new design is string-only with HogQL
# casting at query time.

_NEW_STRING_RANGE_START = 10
_NEW_STRING_RANGE_END = 100  # exclusive

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

operations = [
    # sharded_events / events on DATA nodes (matches migration 0179's split).
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table=EVENTS_DATA_TABLE(),
            start=_NEW_STRING_RANGE_START,
            end_exclusive=_NEW_STRING_RANGE_END,
        ),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table="events",
            start=_NEW_STRING_RANGE_START,
            end_exclusive=_NEW_STRING_RANGE_END,
        ),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
] + (
    [
        # writable_events on INGESTION_EVENTS nodes (matches migration 0232's split for the WS path).
        run_sql_with_exceptions(
            ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
                table="writable_events",
                start=_NEW_STRING_RANGE_START,
                end_exclusive=_NEW_STRING_RANGE_END,
            ),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
    if _is_cloud
    else []
)
