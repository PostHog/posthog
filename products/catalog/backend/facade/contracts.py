from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


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
class CatalogEntityDTO:
    """A business object — Customer, Order, Subscription."""

    id: UUID
    name: str
    description: str | None
    member_node_ids: tuple[UUID, ...]
    status: str
    confidence: float | None
    reasoning: str
    reviewed_at: datetime | None
    discovered_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class CatalogMetricDTO:
    """An aggregation over a column (or row count) — e.g. SUM(stripe_charges.amount)."""

    id: UUID
    name: str
    description: str | None
    entity_id: UUID | None
    node_id: UUID
    column_id: UUID | None
    aggregation: str
    status: str
    confidence: float | None
    reviewed_at: datetime | None
    discovered_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class CatalogDimensionDTO:
    """A column used to group or filter — country, plan_tier, browser."""

    id: UUID
    name: str
    description: str | None
    entity_id: UUID | None
    node_id: UUID
    column_id: UUID
    status: str
    confidence: float | None
    reviewed_at: datetime | None
    discovered_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class CatalogBrowserDTO:
    """Bundles entities, metrics, dimensions, and relationships so the
    entity-grouped browser can fetch its whole world in one round-trip."""

    entities: tuple[CatalogEntityDTO, ...] = field(default_factory=tuple)
    metrics: tuple[CatalogMetricDTO, ...] = field(default_factory=tuple)
    dimensions: tuple[CatalogDimensionDTO, ...] = field(default_factory=tuple)
    relationships: tuple[CatalogRelationshipDTO, ...] = field(default_factory=tuple)
    generated_at: datetime | None = None


@dataclass(frozen=True)
class DeriveResult:
    """Counts returned by the rule-based proposer. Drives the 'we found N proposals' UI."""

    entities_created: int
    metrics_created: int
    dimensions_created: int


@dataclass(frozen=True)
class UpdateEntityParams:
    team_id: int
    entity_id: UUID
    name: str | None = None
    description: str | None = None
    status: str | None = None
    reviewed_by_id: int | None = None


@dataclass(frozen=True)
class UpdateMetricParams:
    team_id: int
    metric_id: UUID
    name: str | None = None
    description: str | None = None
    entity_id: UUID | None = None
    status: str | None = None
    reviewed_by_id: int | None = None


@dataclass(frozen=True)
class UpdateDimensionParams:
    team_id: int
    dimension_id: UUID
    name: str | None = None
    description: str | None = None
    entity_id: UUID | None = None
    status: str | None = None
    reviewed_by_id: int | None = None


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
