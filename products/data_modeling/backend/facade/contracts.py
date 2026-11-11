"""
Cross-boundary data contracts for data_modeling.

Frozen, framework-free dataclasses (``pydantic.dataclasses.dataclass`` — runtime type
validation on construction) describing data_modeling data crossing the product boundary.
ORM models are never returned across the boundary; the facade maps them to these.

data_modeling's external surface is predominantly model-class object wiring (saved-query
DAG traversal, resolvers) re-exported through ``facade.models``; this contract-data
surface is intentionally small and grows as consumers migrate to data reads.
"""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic.dataclasses import dataclass

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from products.warehouse_sources.backend.facade.types import WarehouseColumnAnnotationDescriptionSource


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


@dataclass(frozen=True)
class SavedQuerySummary:
    """A saved query as other products need to see it: enough to name it and query it.

    ``name`` is the HogQL identifier whether or not the view is materialized -- the physical backing
    table is swapped in during resolution and is never the name a caller should query. That is also
    why no materialization flag is exposed here: callers query the name either way.
    """

    id: str
    team_id: int
    name: str
    last_run_at: datetime | None


@dataclass(frozen=True)
class SavedQueryDefinition:
    """A saved query with its HogQL and whether its DAG node materializes."""

    id: UUID
    name: str
    hogql: str
    materializes: bool
    is_test: bool
    is_managed: bool
    origin: str | None
    created_at: datetime
    refreshes_incrementally: bool = False
    calls_decision_functions: bool = False
    created_by_id: int | None = None


@dataclass(frozen=True)
class Dependent:
    """Something that reads a saved query, and what a caller's grants are resolved against."""

    name: str
    kind: str
    saved_query_id: str | None = None
    created_by_id: int | None = None
    lineage_node_id: str | None = None


@frozen
class UpstreamTableRef:
    name: str
    warehouse_table_id: str | None = None
    is_posthog_table: bool = False


@dataclass(frozen=True)
class SuspensionMarker:
    """Why and when scheduled materialization stopped for one engine."""

    at: str
    reason: str
    job_id: str


@dataclass(frozen=True)
class SavedQueryNodeState:
    """What a saved query's DAG nodes record about its schedule."""

    declared_target: timedelta | None
    suspended: dict[str, SuspensionMarker]


@dataclass(frozen=True)
class SavedQuerySchedule:
    """When a materialized saved query is next due, as far as the scheduler's cadence says."""

    interval: timedelta
    # Last successful materialization + interval. Approximate: it is None until the first run has
    # completed, and it drifts if the tier's schedule was paused.
    next_run_at: datetime | None


class MaterializationRefusedError(Exception):
    pass


class IncrementalConfigRefusedError(MaterializationRefusedError):
    def __init__(self, message: str, refused_keys: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.refused_keys = refused_keys


class MaterializationRunDirection(LabeledStrEnum):
    UPSTREAM = "upstream", "Upstream"
    DOWNSTREAM = "downstream", "Downstream"


class MaterializationEngine(LabeledStrEnum):
    CLICKHOUSE = "clickhouse", "ClickHouse"
    TRINO = "trino", "Trino"


class MaterializationForbiddenError(Exception):
    pass


class ManagedWarehouseUnavailableError(MaterializationForbiddenError):
    pass


class MaterializationAlreadyRunningError(Exception):
    pass


class MaterializationRanRecentlyError(Exception):
    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class MaterializationFailedError(Exception):
    pass


class UnknownNodeError(Exception):
    """The node id does not name a live node in the team, so there is nothing to watch."""


@dataclass(frozen=True)
class NodeDescriptionTarget:
    """What a node stands for, which decides where its description lives."""

    node_id: UUID
    saved_query_id: UUID | None = None
    warehouse_table_id: UUID | None = None


@dataclass(frozen=True)
class NodeDescription:
    text: str = ""
    source: WarehouseColumnAnnotationDescriptionSource | None = None


@frozen
class SuspensionSelection:
    """Which suspension markers staff picked to clear. Filters combine with AND."""

    team_id: int | None
    node_ids: tuple[UUID, ...]
    saved_query_ids: tuple[UUID, ...]
    engine: str | None
    reason_contains: tuple[str, ...]
    suspended_from: datetime | None
    suspended_to: datetime | None


@frozen
class SuspensionMarkerSummary:
    node_id: UUID
    node_name: str
    team_id: int
    saved_query_id: UUID | None
    engine: str
    at: str
    reason: str


@frozen
class SuspensionMarkerKey:
    """One marker staff saw in the preview. `at` tells a re-suspension apart from the marker staff reviewed."""

    node_id: UUID
    engine: str
    at: str


@frozen
class SuspensionsCleared:
    cleared: int
    skipped: int


class SuspensionSelectionTooBroadError(Exception):
    pass


@frozen
class UntargetedNode:
    name: str
    node_type: str


@frozen
class NodeRunSummary:
    name: str
    node_type: str
    status: str
    detail: str
    workflow_id: str | None
    workflow_run_id: str | None


@frozen
class TierSummary:
    label: str
    schedule_id: str
    parent_workflow_id: str | None
    started_at: datetime | None
    # The run came from the DAG's pre-tier single schedule, not from this tier's own.
    run_is_legacy: bool
    declared: int
    ran: int
    # Node count per status, worst status first.
    counts: tuple[tuple[str, int], ...]
    nodes: tuple[NodeRunSummary, ...]


@frozen
class DagTierReport:
    """What each cadence tier of one DAG holds and what its last run did, for the staff console."""

    dag_id: UUID
    dag_name: str
    team_id: int
    team_name: str
    sync_frequency_interval: timedelta | None
    tiers: tuple[TierSummary, ...]
    untargeted: tuple[UntargetedNode, ...]
