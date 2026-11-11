"""
Cross-boundary data contracts for data_modeling.

Frozen, framework-free dataclasses (``pydantic.dataclasses.dataclass`` — runtime type
validation on construction) describing data_modeling data crossing the product boundary.
ORM models are never returned across the boundary; the facade maps them to these.

data_modeling's external surface is predominantly model-class object wiring (saved-query
DAG traversal, resolvers) re-exported through ``facade.models``; this contract-data
surface is intentionally small and grows as consumers migrate to data reads.
"""

import dataclasses
from datetime import datetime, timedelta
from typing import Any, Literal, Optional
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


class UnsatisfiableFrequencyError(ValueError):
    """A declared target falls outside the node's legal [source_floor, consumer_ceiling] range."""


class UnsupportedFrequencyTargetError(ValueError):
    """A declared target is not one of the cadences a person may pick (SCHEDULABLE_BUCKETS)."""


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class Bound:
    """A bound and the node that set it, so a refusal can name what someone has to change.

    `blocker` is the node the value originates from, carried across the whole traversal rather
    than the immediate neighbour: a floor propagated down four views still points at the source
    that delivers slowly, which is the thing a person can act on.
    """

    value: timedelta
    blocker: str | None  # None when nothing set it (a derived node with no parents)


BlockedBy = Literal["source", "consumer"]


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class TargetOption:
    """One cadence a person could pick, and why it is withheld when it is."""

    value: timedelta
    allowed: bool
    blocked_by: BlockedBy | None = None
    blocker: str | None = None  # node id of the source or consumer that withholds it


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class TargetBounds:
    """Every selectable cadence for one node, each marked allowed or blocked with its cause.

    `floor` and `ceiling` are reported only when they actually withhold an option. A 5min source
    delivers faster than any tier runs, so it withholds nothing, and reporting it would explain a
    restriction the person cannot see.
    """

    options: tuple[TargetOption, ...]  # ascending by cadence
    floor: Bound | None = None
    ceiling: Bound | None = None

    @property
    def allowed(self) -> tuple[timedelta, ...]:
        return tuple(option.value for option in self.options if option.allowed)

    @property
    def satisfiable(self) -> bool:
        """False when nothing is legal: bounds that cross, or a source slower than every target."""
        return bool(self.allowed)

    def option_for(self, target: timedelta) -> TargetOption | None:
        return next((option for option in self.options if option.value == target), None)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class NodeIdentity:
    """What a node is in access-control terms, so a caller can decide whether to name it.

    All three empty means the node predates the origin stamp, and a caller that redacts should
    treat it as withheld rather than guess.
    """

    saved_query_id: str | None  # views, materialized views and endpoints, under `warehouse_view`
    warehouse_table_id: str | None  # imported source tables, under `warehouse_table`
    is_posthog_table: bool  # `events`, `persons` and friends, readable by anyone on the project


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class SavedQueryFrequencyBounds:
    """A saved query's selectable cadences, plus what a caller needs to name the blockers."""

    bounds: TargetBounds
    names: dict[str, str]  # node id -> display name, covering every blocker the bounds reference
    identities: dict[str, NodeIdentity]  # node id -> the resource its name belongs to
    best_effort_source_ids: set[str]  # upstream sources with no schedule, so the floor is a guess
    max_data_age: timedelta
    speeds_up: dict[timedelta, set[str]]  # cadence -> upstream nodes that would run more often if this were set to it
    pinned: bool


def _nameless_refusal(view_name: str) -> str:
    return f"Can't delete {view_name} yet. Something else reads from it. Update or delete it first."


class HasDependentsError(Exception):
    """Raised when attempting to delete a saved query that has dependents.

    Names no dependent. Only a caller that has filtered `dependents` through the reader's access
    may name one, so a caller that logs or renders `str(err)` cannot disclose one by accident.
    """

    def __init__(
        self,
        view_name: str,
        dependents: tuple[Dependent, ...] = (),
        fallback_node_id: str | None = None,
    ) -> None:
        super().__init__(_nameless_refusal(view_name))
        self.view_name = view_name
        self.dependents = dependents
        self.fallback_node_id = fallback_node_id


class MissingDagNodeError(Exception):
    """Raised when a saved query on a v2 team has no node to schedule through.

    On v2 the node is the unit of execution: the DAG run materializes nodes, so a saved query
    with no node is not reachable by any schedule. Without this the query would be left claiming
    to be materialized while nothing refreshes it.
    """

    pass


class SavedQueryNotFoundError(Exception):
    """Raised by ``run_saved_query_materialization`` when the saved query no longer resolves."""


class SavedQueryNotOnV2ScheduleError(Exception):
    """Raised by ``run_saved_query_materialization`` when the saved query still runs on the older
    per-query schedule, whose frozen workflow lacks what the caller needs from a materialization."""


class SchedulingUnavailableError(Exception):
    """Raised when Temporal is unreachable, so the schedule state of a saved query is unknown.
    The caller decides what to keep, because the saved query itself is not at fault."""


DEFAULT_LOOKBACK_SECONDS = 0


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class IncrementalConfig:
    """The user-declared half of an incremental view."""

    incremental_key: str
    unique_key: tuple[str, ...]
    lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS

    def canonical(self) -> dict[str, Any]:
        """Fingerprint input. Order-insensitive for unique_key, since reordering it changes nothing.

        Deliberately excludes lookback_seconds: it is operational, not definitional. It changes how
        far future runs re-read, not what the stored rows mean, and rows arriving later than any
        lookback are best-effort by design. Widening it does not repair past gaps either way; the
        explicit rebuild action does.
        """
        return {
            "incremental_key": self.incremental_key,
            "unique_key": sorted(self.unique_key),
        }


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class IncrementalState:
    """The system-written half: how far the last successful run got."""

    watermark: Any = None
    watermark_type: Optional[str] = None
    definition_fingerprint: Optional[str] = None
    last_full_refresh_at: Optional[str] = None
    last_run_mode: Optional[str] = None
    has_incremental_history: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class WritePlan:
    """Whether this run rebuilds the table or updates it, and why. The reason is surfaced on the
    job so an unexpectedly expensive run explains itself."""

    incremental: bool
    reason: str
    since: Any = None
    fingerprint: str | None = None
    config: IncrementalConfig | None = None


class IncrementalFilterError(ValueError):
    """The query cannot carry an incremental window filter.

    A user-input problem (a 400), not a server fault: the key column is missing, or it is produced
    by an aggregate and so cannot be filtered before grouping.
    """


@dataclasses.dataclass(frozen=True, kw_only=True)
class EligibilityResult:
    eligible: bool
    key_candidates: list[str] = dataclasses.field(default_factory=list)
    # Columns the unique key may be built from: a superset of key_candidates, since identifying a
    # row only needs equality while the incremental key needs an advancing order.
    unique_key_candidates: list[str] = dataclasses.field(default_factory=list)
    # Coarse type per candidate, for the picker's type tags. Missing entry: type unknown.
    key_candidate_types: dict[str, str] = dataclasses.field(default_factory=dict)
    blockers: list[str] = dataclasses.field(default_factory=list)
    blocked_keys: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
