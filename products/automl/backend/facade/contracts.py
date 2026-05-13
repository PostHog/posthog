"""
Contract types for AutoML.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by the facade as inputs/outputs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from .enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


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
