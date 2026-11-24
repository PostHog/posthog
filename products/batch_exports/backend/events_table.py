"""Which events table a batch export reads.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

from django.conf import settings


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
