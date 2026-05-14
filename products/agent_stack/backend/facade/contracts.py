"""
Contract types for agent_stack.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .enums import SplineStatus


@dataclass(frozen=True)
class SplineReticulatorDTO:
    id: UUID
    name: str
    status: SplineStatus
    created_at: datetime


@dataclass(frozen=True)
class CreateSplineReticulatorInput:
    team_id: int
    name: str
