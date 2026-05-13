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
    """Input to create a new AutoML pipeline. Task-specific shape lives in `config`."""

    team_id: int
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
    created_by_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
