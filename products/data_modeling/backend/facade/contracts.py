"""
Cross-boundary data contracts for data_modeling.

Frozen, framework-free dataclasses (``pydantic.dataclasses.dataclass`` — runtime type
validation on construction) describing data_modeling data crossing the product boundary.
ORM models are never returned across the boundary; the facade maps them to these.

data_modeling's external surface is predominantly model-class object wiring (saved-query
DAG traversal, resolvers) re-exported through ``facade.models``; this contract-data
surface is intentionally small and grows as consumers migrate to data reads.
"""

from datetime import datetime

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class DataModelingJob:
    """A materialization run for a saved query."""

    id: str
    team_id: int | None
    saved_query_id: str | None
    status: str
    engine: str
    rows_materialized: int
    rows_expected: int | None
    error: str | None
    last_run_at: datetime
