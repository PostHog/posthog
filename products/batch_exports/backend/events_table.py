"""Which events table a batch export reads.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

from django.conf import settings

from posthog.models.instance_setting import get_instance_setting


def batch_exports_read_new_events_table(team_id: int) -> bool:
    """Whether the project's batch exports read events_json instead of the legacy events table.

    Only the BATCH_EXPORTS_NEW_EVENTS_SCHEMA_TEAMS instance setting moves an export. The switches that move the rest
    of PostHog (CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS, the
    new-events-table-rollout flag and the project's opt-in) do not, so the rows an export writes to a customer's
    destination change only when the batch exports team moves the project. It reads Postgres, so worker code must
    call it off the event loop.
    """
    # The test suites that run on both tables turn on the new one with this Django setting.
    if settings.TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    raw = str(get_instance_setting("BATCH_EXPORTS_NEW_EVENTS_SCHEMA_TEAMS") or "")
    return team_id in {int(part) for part in raw.split(",") if part.strip()}
