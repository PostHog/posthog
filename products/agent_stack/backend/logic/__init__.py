"""Business logic for agent_stack."""

from __future__ import annotations

from ..facade.enums import SplineStatus
from ..models import SplineReticulator


def create_spline_reticulator(*, team_id: int, name: str) -> SplineReticulator:
    return SplineReticulator.objects.create(team_id=team_id, name=name, status=SplineStatus.PENDING)


def list_spline_reticulators() -> list[SplineReticulator]:
    return list(SplineReticulator.objects.all())
