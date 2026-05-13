"""
Exported enums for AutoML.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

from enum import StrEnum


class TaskType(StrEnum):
    """The four canonical AutoML task types. See `design.md` in the `/phs automl` skill."""

    CLUSTERING = "clustering"
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    FORECASTING = "forecasting"


class PipelineStatus(StrEnum):
    """Lifecycle state of an AutoML pipeline."""

    DRAFT = "draft"
    BOOTSTRAP_PENDING = "bootstrap_pending"
    BOOTSTRAP_RUNNING = "bootstrap_running"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    FAILED = "failed"


class AutonomyLevel(StrEnum):
    """Output autonomy gate. See `io-spec.md` in the `/phs automl` skill."""

    SHADOW_ONLY = "shadow_only"
    CHAMPION_ONLY = "champion_only"
    PROMOTE_ELIGIBLE = "promote_eligible"


class Cadence(StrEnum):
    """Inference and retraining cadence options."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    NEVER = "never"
