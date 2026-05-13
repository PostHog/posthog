"""
Contract types for AutoML.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by the facade as inputs/outputs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from .enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


class ValidationSeverity(StrEnum):
    """Severity tier for a validation finding.

    ``block`` findings prevent pipeline creation; ``warn`` surfaces requires-acknowledgement
    issues; ``info`` is annotative and never gates anything.
    """

    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class AutoMLPipelineDTO:
    """The public shape of an AutoML pipeline."""

    id: UUID
    team_id: int
    name: str
    description: str
    task_type: TaskType
    status: PipelineStatus
    autonomy: AutonomyLevel
    config: dict[str, Any]
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    inference_cadence: Cadence
    retraining_cadence: Cadence
    output_property_name: str
    # System-managed runtime state (bootstrap_task_id, mlflow_run_id, ...).
    # Read-only from the API — populated by the facade's lifecycle methods.
    runtime: dict[str, Any]
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreatePipelineInput:
    """Request body for creating an AutoML pipeline.

    ``team_id`` and ``created_by_id`` are server-injected from the request scope
    and are not part of this DTO. Task-type-specific config lives in ``config``.
    """

    name: str
    task_type: TaskType
    config: dict[str, Any]
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    description: str = ""
    autonomy: AutonomyLevel = AutonomyLevel.CHAMPION_ONLY
    inference_cadence: Cadence = Cadence.DAILY
    retraining_cadence: Cadence = Cadence.DAILY
    output_property_name: str = ""


@dataclass(frozen=True)
class UpdatePipelineInput:
    """Partial-update body for an AutoML pipeline. None means leave unchanged.

    Status transitions go through dedicated facade methods (start / pause /
    resume / archive) so the lifecycle stays explicit.
    """

    name: str | None = None
    description: str | None = None
    autonomy: AutonomyLevel | None = None
    inference_cadence: Cadence | None = None
    retraining_cadence: Cadence | None = None
    output_property_name: str | None = None
    config: dict[str, Any] | None = None
    training_population: dict[str, Any] | None = None
    inference_population: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class PipelineNotFoundError(Exception):
    """Raised by the facade when a pipeline lookup misses."""


class PipelineStateTransitionError(Exception):
    """Raised when a status transition isn't allowed from the current state."""


@dataclass(frozen=True)
class ValidationFinding:
    """One result from preflight validation.

    Findings are emitted by the validate facade method against a proposed pipeline
    config. Callers should treat ``block`` as a hard gate before creating the pipeline,
    ``warn`` as an issue that requires user acknowledgement, and ``info`` as advisory.
    """

    severity: ValidationSeverity
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationSummary:
    """Quantitative summary of a validation run.

    Fields are best-effort: any number derived from a HogQL count query may be
    ``None`` if the underlying query failed or the population kind isn't supported.
    """

    task_type: TaskType
    training_population_kind: str
    estimated_training_rows: int | None = None
    estimated_inference_rows: int | None = None
    estimated_inference_events_per_day: int | None = None
    estimated_positive_count: int | None = None
    estimated_positive_rate: float | None = None
    target_event: str | None = None
    estimated_series_count: int | None = None
    estimated_rows_per_cluster: float | None = None


@dataclass(frozen=True)
class ValidationReport:
    """Result of running preflight validation against a proposed pipeline config.

    ``ok`` is derived from findings — true iff zero ``block`` findings are present.
    Callers should not mutate findings or summary; both are intended for direct
    serialization to the API response.
    """

    ok: bool
    findings: list[ValidationFinding]
    summary: ValidationSummary
