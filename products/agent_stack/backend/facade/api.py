"""
Facade for agent_stack.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from .. import logic
from ..models import SplineReticulator
from . import contracts
from .enums import SplineStatus


def _to_dto(obj: SplineReticulator) -> contracts.SplineReticulatorDTO:
    return contracts.SplineReticulatorDTO(
        id=obj.id,
        name=obj.name,
        status=SplineStatus(obj.status),
        created_at=obj.created_at,
    )


def create(input: contracts.CreateSplineReticulatorInput) -> contracts.SplineReticulatorDTO:
    obj = logic.create_spline_reticulator(team_id=input.team_id, name=input.name)
    return _to_dto(obj)


def list_all() -> list[contracts.SplineReticulatorDTO]:
    return [_to_dto(obj) for obj in logic.list_spline_reticulators()]
