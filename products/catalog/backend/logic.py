from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from products.catalog.backend.facade import contracts
from products.catalog.backend.models import (
    CatalogColumn,
    CatalogDimension,
    CatalogEntity,
    CatalogMetric,
    CatalogNode,
    CatalogRelationship,
)
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable

if TYPE_CHECKING:
    pass


def to_column_dto(column: CatalogColumn) -> contracts.CatalogColumnDTO:
    return contracts.CatalogColumnDTO(
        id=column.id,
        name=column.name,
        position=column.position,
        clickhouse_type=column.clickhouse_type,
        hogql_type=column.hogql_type,
        nullable=column.nullable,
        description=column.synthetic_description,
        semantic_type=column.semantic_type,
        pii_class=column.pii_class,
        confidence=column.confidence,
    )


def to_node_dto(node: CatalogNode, *, columns: list[CatalogColumn] | None = None) -> contracts.CatalogNodeDTO:
    if columns is None:
        columns = list(node.columns.all())
    return contracts.CatalogNodeDTO(
        id=node.id,
        team_id=node.team_id,
        kind=node.kind,
        name=node.name,
        description=node.synthetic_description,
        semantic_role=node.semantic_role,
        business_domain=node.business_domain,
        tags=tuple(node.tags or ()),
        columns=tuple(to_column_dto(c) for c in columns),
        first_seen_at=node.first_seen_at,
        last_seen_at=node.last_seen_at,
        last_traversed_at=node.last_traversed_at,
        confidence=node.confidence,
        status=node.status,
        reviewed_at=node.reviewed_at,
    )


def to_relationship_dto(rel: CatalogRelationship) -> contracts.CatalogRelationshipDTO:
    return contracts.CatalogRelationshipDTO(
        id=rel.id,
        source_node_id=rel.source_node_id,
        source_column=rel.source_column.name if rel.source_column else None,
        target_node_id=rel.target_node_id,
        target_column=rel.target_column.name if rel.target_column else None,
        kind=rel.kind,
        confidence=rel.confidence,
        reasoning=rel.reasoning,
        status=rel.status,
        discovered_at=rel.discovered_at,
        last_seen_at=rel.last_seen_at,
    )


def get_graph(team_id: int) -> contracts.CatalogGraphDTO:
    nodes = list(CatalogNode.objects.filter(team_id=team_id).prefetch_related("columns"))
    relationships = list(
        CatalogRelationship.objects.filter(team_id=team_id).select_related("source_column", "target_column")
    )
    return contracts.CatalogGraphDTO(
        nodes=tuple(to_node_dto(n, columns=list(n.columns.all())) for n in nodes),
        relationships=tuple(to_relationship_dto(r) for r in relationships),
        generated_at=timezone.now(),
    )


def get_node(team_id: int, node_id: UUID) -> contracts.CatalogNodeDTO | None:
    node = CatalogNode.objects.filter(team_id=team_id, id=node_id).prefetch_related("columns").first()
    if node is None:
        return None
    return to_node_dto(node)


def list_nodes(team_id: int) -> list[contracts.CatalogNodeDTO]:
    nodes = list(
        CatalogNode.objects.filter(team_id=team_id).prefetch_related("columns").order_by("business_domain", "name")
    )
    return [to_node_dto(n) for n in nodes]


def get_column(team_id: int, column_id: UUID) -> contracts.CatalogColumnDTO | None:
    column = CatalogColumn.objects.filter(team_id=team_id, id=column_id).first()
    if column is None:
        return None
    return to_column_dto(column)


def get_relationship(team_id: int, relationship_id: UUID) -> contracts.CatalogRelationshipDTO | None:
    rel = (
        CatalogRelationship.objects.filter(team_id=team_id, id=relationship_id)
        .select_related("source_column", "target_column")
        .first()
    )
    if rel is None:
        return None
    return to_relationship_dto(rel)


@transaction.atomic
def upsert_node(params: contracts.UpsertNodeParams) -> contracts.CatalogNodeDTO:
    defaults: dict = {
        "last_traversed_at": timezone.now(),
    }
    if params.synthetic_description is not None:
        defaults["synthetic_description"] = params.synthetic_description
        defaults["description_generated_at"] = timezone.now()
    if params.semantic_role is not None:
        defaults["semantic_role"] = params.semantic_role
    if params.business_domain is not None:
        defaults["business_domain"] = params.business_domain
    if params.tags:
        defaults["tags"] = list(params.tags)
    if params.generator_model is not None:
        defaults["generator_model"] = params.generator_model
    if params.confidence is not None:
        defaults["confidence"] = params.confidence

    if params.warehouse_table_id is not None:
        defaults["content_type"] = ContentType.objects.get_for_model(DataWarehouseTable)
        defaults["object_id"] = params.warehouse_table_id
    elif params.saved_query_id is not None:
        defaults["content_type"] = ContentType.objects.get_for_model(DataWarehouseSavedQuery)
        defaults["object_id"] = params.saved_query_id

    node, _ = CatalogNode.objects.update_or_create(
        team_id=params.team_id,
        kind=params.kind,
        name=params.name,
        defaults=defaults,
    )
    return to_node_dto(node)


@transaction.atomic
def upsert_column(params: contracts.UpsertColumnParams) -> contracts.CatalogColumnDTO:
    node_team_id = CatalogNode.objects.values_list("team_id", flat=True).get(pk=params.node_id)
    defaults: dict = {
        "team_id": node_team_id,  # update_or_create bypasses save(), so set it explicitly
        "position": params.position,
        "clickhouse_type": params.clickhouse_type,
        "hogql_type": params.hogql_type,
        "nullable": params.nullable,
    }
    if params.synthetic_description is not None:
        defaults["synthetic_description"] = params.synthetic_description
        defaults["description_generated_at"] = timezone.now()
    if params.semantic_type is not None:
        defaults["semantic_type"] = params.semantic_type
    if params.pii_class is not None:
        defaults["pii_class"] = params.pii_class
    if params.generator_model is not None:
        defaults["generator_model"] = params.generator_model
    if params.confidence is not None:
        defaults["confidence"] = params.confidence

    column, _ = CatalogColumn.objects.update_or_create(
        node_id=params.node_id,
        name=params.name,
        defaults=defaults,
    )
    return to_column_dto(column)


@transaction.atomic
def propose_relationship(params: contracts.ProposeRelationshipParams) -> contracts.CatalogRelationshipDTO:
    """Insert or update a catalog relationship.

    Status policy:
      - On INSERT, confidence == 1.0 → status=ACCEPTED (declarative claim).
        Any other value → status=PROPOSED (model default, awaits review).
      - On UPDATE, status is never touched. Human review actions (REJECTED,
        STALE) and prior ACCEPTED stick across re-runs.
    """
    defaults: dict = {
        "confidence": params.confidence,
        "reasoning": params.reasoning,
        "discovered_in_run_id": params.discovered_in_run_id,
        "generator_model": params.generator_model,
    }

    rel, created = CatalogRelationship.objects.update_or_create(
        team_id=params.team_id,
        source_node_id=params.source_node_id,
        source_column_id=params.source_column_id,
        target_node_id=params.target_node_id,
        target_column_id=params.target_column_id,
        kind=params.kind,
        defaults=defaults,
    )
    if created and params.confidence == 1.0:
        rel.status = CatalogRelationship.Status.ACCEPTED
        rel.save(update_fields=["status"])
    return to_relationship_dto(rel)


def mark_node_traversed(node_id: UUID, *, now: datetime | None = None) -> None:
    CatalogNode.objects.filter(id=node_id).update(last_traversed_at=now or timezone.now())


# The status values that count as a human review action — they stamp reviewed_at + reviewed_by.
_REVIEW_STATUSES = {CatalogNode.Status.APPROVED, CatalogNode.Status.OFFICIAL}


@transaction.atomic
def update_node(params: contracts.UpdateNodeParams) -> contracts.CatalogNodeDTO | None:
    node = CatalogNode.objects.filter(team_id=params.team_id, id=params.node_id).first()
    if node is None:
        return None

    if params.name is not None:
        node.name = params.name
    if params.synthetic_description is not None:
        node.synthetic_description = params.synthetic_description
    if params.semantic_role is not None:
        node.semantic_role = params.semantic_role
    if params.business_domain is not None:
        node.business_domain = params.business_domain
    if params.tags is not None:
        node.tags = list(params.tags)
    if params.confidence is not None:
        node.confidence = params.confidence
    if params.status is not None:
        node.status = params.status
        if params.status in _REVIEW_STATUSES and params.reviewed_by_id is not None:
            node.reviewed_by_id = params.reviewed_by_id
            node.reviewed_at = timezone.now()

    node.save()
    return to_node_dto(node)


@transaction.atomic
def update_column(params: contracts.UpdateColumnParams) -> contracts.CatalogColumnDTO | None:
    column = CatalogColumn.objects.filter(team_id=params.team_id, id=params.column_id).first()
    if column is None:
        return None

    if params.synthetic_description is not None:
        column.synthetic_description = params.synthetic_description
    if params.semantic_type is not None:
        column.semantic_type = params.semantic_type
    if params.pii_class is not None:
        column.pii_class = params.pii_class
    if params.confidence is not None:
        column.confidence = params.confidence

    column.save()
    return to_column_dto(column)


@transaction.atomic
def update_relationship(params: contracts.UpdateRelationshipParams) -> contracts.CatalogRelationshipDTO | None:
    rel = CatalogRelationship.objects.filter(team_id=params.team_id, id=params.relationship_id).first()
    if rel is None:
        return None

    if params.status is not None:
        rel.status = params.status
        if params.status == CatalogRelationship.Status.ACCEPTED and params.reviewed_by_id is not None:
            rel.reviewed_by_id = params.reviewed_by_id
            rel.reviewed_at = timezone.now()
    if params.confidence is not None:
        rel.confidence = params.confidence
    if params.reasoning is not None:
        rel.reasoning = params.reasoning

    rel.save()
    return to_relationship_dto(rel)


# --- Entity / Metric / Dimension DTOs ---------------------------------------


def to_entity_dto(entity: CatalogEntity, *, member_node_ids: list[UUID] | None = None) -> contracts.CatalogEntityDTO:
    ids = member_node_ids if member_node_ids is not None else list(entity.member_nodes.values_list("id", flat=True))
    return contracts.CatalogEntityDTO(
        id=entity.id,
        name=entity.name,
        description=entity.description,
        member_node_ids=tuple(ids),
        status=entity.status,
        confidence=entity.confidence,
        reasoning=entity.reasoning,
        reviewed_at=entity.reviewed_at,
        discovered_at=entity.discovered_at,
        last_seen_at=entity.last_seen_at,
    )


def to_metric_dto(metric: CatalogMetric) -> contracts.CatalogMetricDTO:
    return contracts.CatalogMetricDTO(
        id=metric.id,
        name=metric.name,
        description=metric.description,
        entity_id=metric.entity_id,
        node_id=metric.node_id,
        column_id=metric.column_id,
        aggregation=metric.aggregation,
        status=metric.status,
        confidence=metric.confidence,
        reviewed_at=metric.reviewed_at,
        discovered_at=metric.discovered_at,
        last_seen_at=metric.last_seen_at,
    )


def to_dimension_dto(dimension: CatalogDimension) -> contracts.CatalogDimensionDTO:
    return contracts.CatalogDimensionDTO(
        id=dimension.id,
        name=dimension.name,
        description=dimension.description,
        entity_id=dimension.entity_id,
        node_id=dimension.node_id,
        column_id=dimension.column_id,
        status=dimension.status,
        confidence=dimension.confidence,
        reviewed_at=dimension.reviewed_at,
        discovered_at=dimension.discovered_at,
        last_seen_at=dimension.last_seen_at,
    )


# --- List + browser bundle --------------------------------------------------


def list_entities(team_id: int) -> list[contracts.CatalogEntityDTO]:
    entities = list(CatalogEntity.objects.filter(team_id=team_id).prefetch_related("member_nodes").order_by("name"))
    return [to_entity_dto(e, member_node_ids=[n.id for n in e.member_nodes.all()]) for e in entities]


def list_metrics(team_id: int) -> list[contracts.CatalogMetricDTO]:
    metrics = list(CatalogMetric.objects.filter(team_id=team_id).order_by("entity_id", "name"))
    return [to_metric_dto(m) for m in metrics]


def list_dimensions(team_id: int) -> list[contracts.CatalogDimensionDTO]:
    dimensions = list(CatalogDimension.objects.filter(team_id=team_id).order_by("entity_id", "name"))
    return [to_dimension_dto(d) for d in dimensions]


def get_browser(team_id: int) -> contracts.CatalogBrowserDTO:
    """Single fetch backing the entity-grouped browser scene."""
    entities = list_entities(team_id)
    metrics = list_metrics(team_id)
    dimensions = list_dimensions(team_id)
    relationships = list(
        CatalogRelationship.objects.filter(team_id=team_id).select_related("source_column", "target_column")
    )
    return contracts.CatalogBrowserDTO(
        entities=tuple(entities),
        metrics=tuple(metrics),
        dimensions=tuple(dimensions),
        relationships=tuple(to_relationship_dto(r) for r in relationships),
        generated_at=timezone.now(),
    )


# --- Rule-based derivation --------------------------------------------------
#
# These functions build entities / metrics / dimensions from the existing
# catalog state (semantic-typed columns and same_entity relationships). No AI
# involved — just structural rules with high confidence. Anything more
# subjective lands in `proposed` for review.


_MEASURE_AGGREGATIONS: dict[str, list[str]] = {
    # monetary columns get SUM by default; AVG is also usually meaningful but
    # one proposal per column is plenty for v1.
    "monetary": ["sum"],
    "measure": ["sum"],
}


def _humanize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip().title()


@transaction.atomic
def derive_catalog(team_id: int, *, generator_model: str | None = None) -> contracts.DeriveResult:
    """Run the rule-based proposer for entities, metrics, and dimensions.

    Idempotent: re-running won't create duplicates because every model has a
    unique constraint on its natural key. Existing rows keep their status —
    only the row's `last_seen_at` updates.
    """
    return contracts.DeriveResult(
        entities_created=_derive_entities(team_id, generator_model=generator_model),
        metrics_created=_derive_metrics(team_id, generator_model=generator_model),
        dimensions_created=_derive_dimensions(team_id, generator_model=generator_model),
    )


def _derive_entities(team_id: int, *, generator_model: str | None) -> int:
    """Cluster nodes by `same_entity` relationships; each cluster becomes an entity.

    A node that doesn't appear in any same_entity relationship still becomes
    its own single-member entity — every business object should be addressable
    by name in the browser.
    """
    nodes = list(CatalogNode.objects.filter(team_id=team_id))
    if not nodes:
        return 0

    parent: dict[UUID, UUID] = {n.id: n.id for n in nodes}

    def find(x: UUID) -> UUID:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    same_entity_edges = CatalogRelationship.objects.filter(
        team_id=team_id, kind=CatalogRelationship.Kind.SAME_ENTITY, status=CatalogRelationship.Status.ACCEPTED
    ).values_list("source_node_id", "target_node_id")
    for source_id, target_id in same_entity_edges:
        if source_id in parent and target_id in parent:
            union(source_id, target_id)

    clusters: dict[UUID, list[CatalogNode]] = {}
    for node in nodes:
        clusters.setdefault(find(node.id), []).append(node)

    created = 0
    for member_nodes in clusters.values():
        # Pick the alphabetically-first warehouse table name when present,
        # otherwise the first member node. Humans can rename.
        warehouse_members = sorted(
            (n for n in member_nodes if n.kind == CatalogNode.Kind.WAREHOUSE_TABLE), key=lambda n: n.name
        )
        canonical = warehouse_members[0] if warehouse_members else min(member_nodes, key=lambda n: n.name)
        entity, was_created = CatalogEntity.objects.get_or_create(
            team_id=team_id,
            name=_humanize(canonical.name),
            defaults={
                "description": f"Proposed from same_entity clustering across {len(member_nodes)} node(s).",
                "confidence": 1.0 if len(member_nodes) > 1 else 0.6,
                "reasoning": f"Cluster root: {canonical.name}; members: {', '.join(n.name for n in member_nodes)}.",
                "generator_model": generator_model,
            },
        )
        # Membership is the source of truth for clustering — always sync, even
        # for existing entities, so newly-linked nodes are added.
        entity.member_nodes.set([n.id for n in member_nodes])
        if was_created:
            created += 1
    return created


def _derive_metrics(team_id: int, *, generator_model: str | None) -> int:
    """One metric proposal per (measure/monetary column, aggregation)."""
    columns = CatalogColumn.objects.filter(
        team_id=team_id, semantic_type__in=[CatalogColumn.SemanticType.MEASURE, CatalogColumn.SemanticType.MONETARY]
    ).select_related("node")

    # Cache entity-per-node so we attach metrics to the right entity.
    entity_for_node: dict[UUID, UUID] = {}
    for entity in CatalogEntity.objects.filter(team_id=team_id).prefetch_related("member_nodes"):
        for node_id in entity.member_nodes.values_list("id", flat=True):
            entity_for_node[node_id] = entity.id

    created = 0
    for column in columns:
        aggregations = _MEASURE_AGGREGATIONS.get(column.semantic_type or "", [])
        for aggregation in aggregations:
            metric, was_created = CatalogMetric.objects.get_or_create(
                team_id=team_id,
                node_id=column.node_id,
                column_id=column.id,
                aggregation=aggregation,
                defaults={
                    "name": f"{aggregation}_{column.name}".lower(),
                    "description": f"Auto-proposed from {column.semantic_type} column `{column.name}`.",
                    "entity_id": entity_for_node.get(column.node_id),
                    "confidence": 0.7,
                    "generator_model": generator_model,
                },
            )
            if was_created:
                created += 1
    return created


def _derive_dimensions(team_id: int, *, generator_model: str | None) -> int:
    """One dimension proposal per (dimension/enum column)."""
    columns = CatalogColumn.objects.filter(
        team_id=team_id, semantic_type__in=[CatalogColumn.SemanticType.DIMENSION, CatalogColumn.SemanticType.ENUM]
    ).select_related("node")

    entity_for_node: dict[UUID, UUID] = {}
    for entity in CatalogEntity.objects.filter(team_id=team_id).prefetch_related("member_nodes"):
        for node_id in entity.member_nodes.values_list("id", flat=True):
            entity_for_node[node_id] = entity.id

    created = 0
    for column in columns:
        dimension, was_created = CatalogDimension.objects.get_or_create(
            team_id=team_id,
            node_id=column.node_id,
            column_id=column.id,
            defaults={
                "name": column.name,
                "description": column.synthetic_description or f"Auto-proposed from {column.semantic_type} column.",
                "entity_id": entity_for_node.get(column.node_id),
                "confidence": 0.7,
                "generator_model": generator_model,
            },
        )
        if was_created:
            created += 1
    return created


# --- Partial updates --------------------------------------------------------


_ENTITY_REVIEW_STATUSES = {CatalogEntity.Status.ACCEPTED, CatalogEntity.Status.REJECTED}
_METRIC_REVIEW_STATUSES = {CatalogMetric.Status.ACCEPTED, CatalogMetric.Status.REJECTED}
_DIMENSION_REVIEW_STATUSES = {CatalogDimension.Status.ACCEPTED, CatalogDimension.Status.REJECTED}


@transaction.atomic
def update_entity(params: contracts.UpdateEntityParams) -> contracts.CatalogEntityDTO | None:
    entity = CatalogEntity.objects.filter(team_id=params.team_id, id=params.entity_id).first()
    if entity is None:
        return None
    if params.name is not None:
        entity.name = params.name
    if params.description is not None:
        entity.description = params.description
    if params.status is not None:
        entity.status = params.status
        if params.status in _ENTITY_REVIEW_STATUSES and params.reviewed_by_id is not None:
            entity.reviewed_by_id = params.reviewed_by_id
            entity.reviewed_at = timezone.now()
    entity.save()
    return to_entity_dto(entity)


@transaction.atomic
def update_metric(params: contracts.UpdateMetricParams) -> contracts.CatalogMetricDTO | None:
    metric = CatalogMetric.objects.filter(team_id=params.team_id, id=params.metric_id).first()
    if metric is None:
        return None
    if params.name is not None:
        metric.name = params.name
    if params.description is not None:
        metric.description = params.description
    if params.entity_id is not None:
        metric.entity_id = params.entity_id
    if params.status is not None:
        metric.status = params.status
        if params.status in _METRIC_REVIEW_STATUSES and params.reviewed_by_id is not None:
            metric.reviewed_by_id = params.reviewed_by_id
            metric.reviewed_at = timezone.now()
    metric.save()
    return to_metric_dto(metric)


@transaction.atomic
def update_dimension(params: contracts.UpdateDimensionParams) -> contracts.CatalogDimensionDTO | None:
    dimension = CatalogDimension.objects.filter(team_id=params.team_id, id=params.dimension_id).first()
    if dimension is None:
        return None
    if params.name is not None:
        dimension.name = params.name
    if params.description is not None:
        dimension.description = params.description
    if params.entity_id is not None:
        dimension.entity_id = params.entity_id
    if params.status is not None:
        dimension.status = params.status
        if params.status in _DIMENSION_REVIEW_STATUSES and params.reviewed_by_id is not None:
            dimension.reviewed_by_id = params.reviewed_by_id
            dimension.reviewed_at = timezone.now()
    dimension.save()
    return to_dimension_dto(dimension)
