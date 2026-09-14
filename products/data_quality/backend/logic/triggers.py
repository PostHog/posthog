"""Gates the event-driven triggers consult before starting a check suite.

Called from other products' pipelines (via inversion hooks or facade functions), so they must be
cheap, never raise, and answer the do-nothing value when the product flag is off.
"""

import uuid
from collections.abc import Iterable

from products.data_modeling.backend.facade import api as data_modeling_facade

from ..facade.contracts import QUALITY_AUDIT_GATE, QUALITY_AUDIT_SKIP, QUALITY_AUDIT_WARN, QualityAuditMode
from ..facade.enums import CheckSeverity
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


def materialization_audit_mode(team_id: int, saved_query_id: "str | uuid.UUID") -> QualityAuditMode:
    """Gating needs an error-severity check as well as the team setting, because a warn-severity
    failure cannot stop a publish and holding one behind an audit would only add latency.
    """
    from ..models import (  # noqa: PLC0415 — the app registry is not ready at import time
        DataQualityCheck,
        TeamDataQualityConfig,
    )

    if not is_data_quality_checks_enabled_for_team_id(team_id):
        return QUALITY_AUDIT_SKIP
    checks = DataQualityCheck.objects.for_team(team_id).filter(
        saved_query_id=saved_query_id, enabled=True, deleted=False
    )
    if not checks.exists():
        return QUALITY_AUDIT_SKIP
    config = TeamDataQualityConfig.objects.filter(team_id=team_id).first()
    gate_on = config is not None and config.gate_materialization_on_checks
    if gate_on and checks.filter(severity=CheckSeverity.ERROR).exists():
        return QUALITY_AUDIT_GATE
    return QUALITY_AUDIT_WARN
