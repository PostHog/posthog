"""
Cross-boundary data contracts for data_warehouse.

Frozen, framework-free dataclasses (``pydantic.dataclasses.dataclass`` — runtime type
validation on construction) describing the data_warehouse data crossing the product
boundary. ORM models are never returned across the boundary; the facade maps them to
these contracts.

data_warehouse's external surface is predominantly operational wiring (schedule/S3/
source-management ops, re-exported through ``facade.api`` and the other submodules), so
the contract-data surface here is intentionally small and grows as consumers migrate
from model objects to data reads.
"""

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TeamDataWarehouseConfig:
    """A team's data-warehouse configuration (the data-ops overview surface)."""

    team_id: int
    overview_dashboard_ids: list[int]
