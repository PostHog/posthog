"""Which events table a batch export reads.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import contextlib
import collections.abc

from django.conf import settings

from posthog.schema import HogQLQueryModifiers

from posthog.models.event.new_events_schema import events_route_scope


def batch_exports_read_new_events_table() -> bool:
    """Whether batch exports read events_json instead of the legacy events table.

    The switches that move the rest of PostHog (CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA,
    CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS, the new-events-table-rollout flag and a project's opt-in) do not
    move a batch export, because the rows an export writes to a customer's destination must change only when the
    batch exports team moves it. Outside tests every export reads the legacy table; the batch exports team adds its
    own switch here.
    """
    # The test suites that run on both tables turn on the new one with this Django setting.
    return settings.TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA


@contextlib.asynccontextmanager
async def route_to_events_table_cluster(reads_new_events_table: bool | None) -> collections.abc.AsyncIterator[None]:
    """A ClickHouse client opened inside connects to the cluster that stores the events table the export reads.

    Without it, the client follows the project's table, which a batch export does not follow. `None` is for an export
    that reads no events: its client keeps following the project. It is async so that it can share one `async with`
    statement with the client.
    """
    if reads_new_events_table is None:
        yield
        return
    with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=reads_new_events_table)):
        yield
