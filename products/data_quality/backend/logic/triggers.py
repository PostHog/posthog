"""Gates the event-driven triggers consult before starting a check suite.

Called from other products' pipelines (via inversion hooks), so they must be cheap, never raise,
and answer false when the product flag is off.
"""

import uuid
from collections.abc import Iterable

from products.data_modeling.backend.facade import api as data_modeling_facade

from .flags import is_data_quality_checks_enabled_for_team_id


def source_sync_checks_needed(team_id: int, table_id: "str | uuid.UUID") -> bool:
    """Whether a completed sync of this table should start a check suite."""
    from ..models import DataQualityCheck  # noqa: PLC0415 — the app registry is not ready at import time

    if not is_data_quality_checks_enabled_for_team_id(team_id):
        return False
    return DataQualityCheck.objects.for_team(team_id).filter(table_id=table_id, enabled=True, deleted=False).exists()


def materialization_checks_needed(team_id: int, node_ids: Iterable["str | uuid.UUID"]) -> bool:
    """Whether a DAG run that materialized these nodes should start a check suite."""
    from ..models import DataQualityCheck  # noqa: PLC0415 — the app registry is not ready at import time

    if not is_data_quality_checks_enabled_for_team_id(team_id):
        return False
    saved_query_ids = data_modeling_facade.get_saved_query_ids_for_nodes(team_id, node_ids)
    if not saved_query_ids:
        return False
    return (
        DataQualityCheck.objects.for_team(team_id)
        .filter(saved_query_id__in=saved_query_ids, enabled=True, deleted=False)
        .exists()
    )
