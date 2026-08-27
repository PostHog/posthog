"""
Facade for data_catalog.

The only module this product's presentation layer (and external code) may import. It re-exports the
logic surface and model classes so the isolation boundary stays clean: presentation never reaches
into ``logic`` or ``models`` directly.
"""

from ..logic.certifications import (
    certifications_for_team,
    certify,
    deprecate,
    propose_certification,
    revoke_certification,
)
from ..logic.drift import compute_drift
from ..logic.execution import run_metric
from ..logic.metrics import (
    BULK_SKIP_NOT_FOUND,
    METRIC_BULK_MAX,
    MetricBulkSkip,
    approve_metric,
    approved_metric_names_for_team,
    bulk_approve_metrics,
    bulk_soft_delete_metrics,
    metrics_for_team,
    refresh_metric_from_insight,
    soft_delete_metric,
    update_metric,
    upsert_metric,
)
from ..logic.relationships import accept_proposal, propose_relationship, reject_proposal, relationships_for_team
from ..logic.validation import MAX_DESCRIPTION_LENGTH, validate_metric_definition
from ..models import METRIC_NAME_MAX_LENGTH
from .models import Metric, RelationshipProposal, TableCertification

__all__ = [
    "BULK_SKIP_NOT_FOUND",
    "MAX_DESCRIPTION_LENGTH",
    "METRIC_BULK_MAX",
    "METRIC_NAME_MAX_LENGTH",
    "Metric",
    "MetricBulkSkip",
    "RelationshipProposal",
    "TableCertification",
    "accept_proposal",
    "approve_metric",
    "approved_metric_names_for_team",
    "bulk_approve_metrics",
    "bulk_soft_delete_metrics",
    "certifications_for_team",
    "certify",
    "compute_drift",
    "deprecate",
    "metrics_for_team",
    "propose_certification",
    "propose_relationship",
    "refresh_metric_from_insight",
    "reject_proposal",
    "relationships_for_team",
    "revoke_certification",
    "run_metric",
    "soft_delete_metric",
    "update_metric",
    "upsert_metric",
    "validate_metric_definition",
]
