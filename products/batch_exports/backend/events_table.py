"""Which events table a batch export reads.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import hashlib

from django.conf import settings


def batch_exports_read_new_events_table(team_id: int, *, export_opted_in: bool = False) -> bool:
    """Whether a batch export reads events_json instead of the legacy events table.

    The switches that move the rest of PostHog (CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA,
    CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS, the new-events-table-rollout flag and a project's opt-in) do not
    move a batch export, because the rows an export writes to a customer's destination must change only when the
    user or the batch exports team moves it. These move it instead, and the first that applies wins:

    1. `export_opted_in`, the `use_new_events_schema` key of the export's destination config, moves the export. A
       user sets it to move one export early, for example a test export next to a production one.
    2. A team in BATCH_EXPORTS_NEW_EVENTS_TABLE_EXCLUDED_TEAM_IDS stays on the legacy table.
    3. A team in BATCH_EXPORTS_NEW_EVENTS_TABLE_TEAM_IDS moves.
    4. Any other team moves when its rollout bucket is below BATCH_EXPORTS_NEW_EVENTS_TABLE_ROLLOUT_PERCENTAGE.
    """
    if export_opted_in:
        return True
    team = str(team_id)
    if team in settings.BATCH_EXPORTS_NEW_EVENTS_TABLE_EXCLUDED_TEAM_IDS:
        return False
    if team in settings.BATCH_EXPORTS_NEW_EVENTS_TABLE_TEAM_IDS:
        return True
    return _get_rollout_bucket(team_id) < settings.BATCH_EXPORTS_NEW_EVENTS_TABLE_ROLLOUT_PERCENTAGE


def _get_rollout_bucket(team_id: int) -> int:
    """A stable bucket from 0 to 99 for the team.

    The salt keeps this rollout from moving the same teams first as another rollout that buckets team ids.
    """
    digest = hashlib.sha256(f"batch-exports-new-events-table:{team_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100
