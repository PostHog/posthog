"""
Facade for data_catalog.

The only module this product's presentation layer (and external code) may import. It re-exports the
logic surface and model classes so the isolation boundary stays clean: presentation never reaches
into ``logic`` or ``models`` directly.
"""

from ..logic.drift import compute_drift
from ..logic.metrics import (
    approve_metric,
    metrics_for_team,
    refresh_metric_from_insight,
    soft_delete_metric,
    update_metric,
    upsert_metric,
)
from ..logic.validation import validate_metric_definition
from .models import Metric

__all__ = [
    "Metric",
    "approve_metric",
    "compute_drift",
    "metrics_for_team",
    "refresh_metric_from_insight",
    "soft_delete_metric",
    "update_metric",
    "upsert_metric",
    "validate_metric_definition",
]
