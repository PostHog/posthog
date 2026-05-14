from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import RootModel

from posthog.schema import DataWarehouseNode, EventsNode, HogQLQuery


class MetricDefinitionSchema(RootModel[EventsNode | DataWarehouseNode | HogQLQuery]):
    """Schema for `CatalogMetric.definition` — same shape as an `Insight.query.series` item.

    A metric is computed from exactly one of: an event count (EventsNode), a data-warehouse
    aggregate (DataWarehouseNode), or a raw HogQL query (HogQLQuery). All three carry a
    `kind` discriminator so consumers can route on shape without parsing the body.
    """

    root: EventsNode | DataWarehouseNode | HogQLQuery


@dataclass(frozen=True)
class CatalogColumnDTO:
    id: UUID
    name: str
    position: int
    clickhouse_type: str | None
    hogql_type: str | None
    nullable: bool
    description: str | None
    semantic_type: str | None
    pii_class: str | None
    confidence: float | None


@dataclass(frozen=True)
class CatalogNodeDTO:
    id: UUID
    team_id: int
    kind: str
    name: str
    description: str | None
    semantic_role: str | None
    business_domain: str | None
    tags: tuple[str, ...]
    columns: tuple[CatalogColumnDTO, ...]
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_traversed_at: datetime | None
    confidence: float | None
    status: str
    reviewed_at: datetime | None


@dataclass(frozen=True)
class CatalogRelationshipDTO:
    id: UUID
    source_node_id: UUID
    source_column: str | None
    target_node_id: UUID
    target_column: str | None
    kind: str
    confidence: float
    reasoning: str
    status: str
    discovered_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class CatalogGraphDTO:
    nodes: tuple[CatalogNodeDTO, ...] = field(default_factory=tuple)
    relationships: tuple[CatalogRelationshipDTO, ...] = field(default_factory=tuple)
    generated_at: datetime | None = None


@dataclass(frozen=True)
class UpsertNodeParams:
    team_id: int
    kind: str
    name: str
    # Optional binding to a backing Django row — only meaningful for
    # warehouse_table / saved_query nodes. The facade writes the matching link
    # row when these are set.
    warehouse_table_id: UUID | None = None
    saved_query_id: UUID | None = None
    synthetic_description: str | None = None
    semantic_role: str | None = None
    business_domain: str | None = None
    tags: tuple[str, ...] = ()
    generator_model: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class UpsertColumnParams:
    node_id: UUID
    name: str
    position: int = 0
    clickhouse_type: str | None = None
    hogql_type: str | None = None
    nullable: bool = True
    synthetic_description: str | None = None
    semantic_type: str | None = None
    pii_class: str | None = None
    generator_model: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class UpdateNodeParams:
    """Partial update of a CatalogNode. Only fields supplied are written."""

    team_id: int
    node_id: UUID
    name: str | None = None
    synthetic_description: str | None = None
    semantic_role: str | None = None
    business_domain: str | None = None
    tags: tuple[str, ...] | None = None
    confidence: float | None = None
    status: str | None = None
    reviewed_by_id: int | None = None


@dataclass(frozen=True)
class UpdateColumnParams:
    """Partial update of a CatalogColumn. Only fields supplied are written."""

    team_id: int
    column_id: UUID
    synthetic_description: str | None = None
    semantic_type: str | None = None
    pii_class: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class UpdateRelationshipParams:
    """Partial update of a CatalogRelationship — primarily for approving/rejecting proposals."""

    team_id: int
    relationship_id: UUID
    status: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    reviewed_by_id: int | None = None


@dataclass(frozen=True)
class CatalogMetricDTO:
    """A semantic metric proposed for the catalog (e.g. "MRR", "DAU", "pricing-page conversion").

    Pairs 1:1 with a `CatalogNode(kind=metric)`, bundled here so the UI gets review
    state (status, confidence, tags, semantic_role, business_domain) without a second
    fetch. Definition lives on the metric row; everything review-related lives on the node.
    Status changes route through PATCH /catalog/nodes/:node.id/ — partial_update on the
    metric endpoint only touches metric-row fields (description, definition).
    """

    id: UUID
    team_id: int
    name: str
    description: str
    definition: dict[str, Any]
    node: CatalogNodeDTO
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class UpdateMetricParams:
    """Partial update of a CatalogMetric. Only fields supplied are written.

    Status / tags / semantic metadata live on the bound CatalogNode and are updated via
    PATCH /catalog/nodes/:id/ with the metric DTO's `node.id`.
    """

    team_id: int
    metric_id: UUID
    description: str | None = None
    definition: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpsertMetricParams:
    """Create or update a CatalogMetric and its bound CatalogNode(kind=metric).

    Idempotent on (team, name): re-calling with the same name updates description and
    definition in place. The bound CatalogNode is created on first insert and reused on
    update. Agent traversal runs call this repeatedly without piling up duplicates.
    """

    team_id: int
    name: str
    description: str = ""
    definition: dict[str, Any] = field(default_factory=dict)
    generator_model: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ProposeRelationshipParams:
    """Write a candidate relationship to the catalog.

    `confidence == 1.0` is treated as a declarative claim — the facade writes
    `status=ACCEPTED` on first insert. Any other value writes `status=PROPOSED`
    (Django's model default), leaving the edge for human review.

    Re-proposing an existing edge never changes its status, regardless of
    confidence — preserves human review actions (REJECTED, STALE) across
    re-runs of the catalog traversal.
    """

    team_id: int
    source_node_id: UUID
    target_node_id: UUID
    kind: str
    confidence: float
    source_column_id: UUID | None = None
    target_column_id: UUID | None = None
    reasoning: str = ""
    discovered_in_run_id: UUID | None = None
    generator_model: str | None = None


@dataclass(frozen=True)
class CatalogNodeContextDTO:
    """Compact view of a CatalogNode + its columns + edges, for read-side injection.

    Returned by `CatalogAPI.get_node_context` and surfaced verbatim into
    `read_data` / `execute_sql` tool output so PostHog AI sees the catalog's
    description alongside any table it touches.
    """

    kind: str
    name: str
    description: str | None  # CatalogNode.synthetic_description, may contain attribution lines
    columns: tuple["CatalogColumnContextDTO", ...]
    outgoing_joins: tuple["CatalogJoinContextDTO", ...]
    incoming_joins: tuple["CatalogJoinContextDTO", ...]


@dataclass(frozen=True)
class CatalogColumnContextDTO:
    name: str
    description: str | None  # CatalogColumn.synthetic_description


@dataclass(frozen=True)
class CatalogJoinContextDTO:
    """A declared / declared-join CatalogRelationship in one of the two directions
    (outgoing/incoming) relative to the queried node. Used by read-side injection
    so the agent can see how a touched table joins to others without a separate
    catalog query."""

    other_table: str
    self_column: str | None
    other_column: str | None
    kind: str
    reasoning: str  # full text incl. any attribution lines


@dataclass(frozen=True)
class AppendNodeNoteParams:
    """Append a user-attributed note to a CatalogNode's synthetic_description.

    Used when PostHog AI learns something about a table during a chat. The tool
    resolves `table_name` to a HogQL table to determine the catalog `kind`, then
    appends the formatted attribution + note to whatever description already
    exists. Idempotent on (team, kind, name) — the node is upserted if missing
    so notes can land even before the traversal workflow has cataloged the
    table.
    """

    team_id: int
    table_name: str
    note: str
    attribution: str  # e.g. "[@aspicer 2026-05-14]" — caller-formatted, embedded verbatim


@dataclass(frozen=True)
class AppendColumnNoteParams:
    """Append a user-attributed note to a CatalogColumn's synthetic_description.

    Same shape as AppendNodeNoteParams but targeting a specific column on a
    table. The CatalogColumn row is upserted on the parent CatalogNode if it
    doesn't exist yet.
    """

    team_id: int
    table_name: str
    column_name: str
    note: str
    attribution: str


@dataclass(frozen=True)
class RecordJoinParams:
    """Record a user-declared join between two catalog tables.

    Writes a CatalogRelationship with kind=declared_join and confidence=1.0
    (auto-accepts on insert per the existing propose_relationship semantics).
    The note + attribution land in the `reasoning` field; re-recording the
    same edge appends a new line to reasoning instead of overwriting it.
    Source and target tables are upserted as CatalogNodes if missing; column
    references are optional (null for table-level lineage).
    """

    team_id: int
    source_table: str
    target_table: str
    note: str
    attribution: str
    source_column: str | None = None
    target_column: str | None = None
