"""Gates the event-driven triggers consult before starting a check suite.

Called from other products' pipelines (via inversion hooks), so they must be cheap, never raise,
and answer false when the product flag is off.
"""

import uuid

from .flags import is_data_quality_checks_enabled_for_team_id


def source_sync_checks_needed(team_id: int, table_id: "str | uuid.UUID") -> bool:
    """Whether a completed sync of this table should start a check suite."""
    # Deferred so this module imports before the app registry is ready.
    from ..models import DataQualityCheck  # noqa: PLC0415

    if not is_data_quality_checks_enabled_for_team_id(team_id):
        return False
    return DataQualityCheck.objects.for_team(team_id).filter(table_id=table_id, enabled=True, deleted=False).exists()
