from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from products.catalog.backend.facade import contracts
from products.catalog.backend.models import CatalogColumn, CatalogMetric, CatalogNode, CatalogRelationship
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


def to_metric_dto(metric: CatalogMetric, node: CatalogNode) -> contracts.CatalogMetricDTO:
    return contracts.CatalogMetricDTO(
        id=metric.id,
        team_id=metric.team_id,
        name=metric.name,
        description=metric.description,
        definition=metric.definition or {},
        node=to_node_dto(node),
        created_at=metric.created_at,
        updated_at=metric.updated_at,
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


def _metric_nodes_by_metric_id(team_id: int, metric_ids: list[UUID]) -> dict[UUID, CatalogNode]:
    """Fetch each metric row's bound CatalogNode(kind=metric) in one query.

    Returned mapping is keyed by CatalogMetric.id (the node's `object_id` via the
    GenericForeignKey). Metrics without a bound node are omitted — callers decide
    whether to skip them or raise. `columns` is prefetched so to_node_dto doesn't
    issue per-row queries when the metric is bundled into a DTO.
    """
    if not metric_ids:
        return {}
    metric_ct = ContentType.objects.get_for_model(CatalogMetric)
    nodes = CatalogNode.objects.filter(
        team_id=team_id,
        kind=CatalogNode.Kind.METRIC,
        content_type=metric_ct,
        object_id__in=metric_ids,
    ).prefetch_related("columns")
    return {node.object_id: node for node in nodes if node.object_id is not None}


def list_metrics(team_id: int) -> list[contracts.CatalogMetricDTO]:
    metrics = list(CatalogMetric.objects.filter(team_id=team_id).order_by("name"))
    node_by_metric = _metric_nodes_by_metric_id(team_id, [m.id for m in metrics])
    # Skip rows whose bound node has been deleted — they're zombies; the cleanup
    # signal hasn't run yet or the node was force-removed. Don't surface them to
    # callers expecting a `node`.
    return [to_metric_dto(m, node=node_by_metric[m.id]) for m in metrics if m.id in node_by_metric]


def get_metric(team_id: int, metric_id: UUID) -> contracts.CatalogMetricDTO | None:
    metric = CatalogMetric.objects.filter(team_id=team_id, id=metric_id).first()
    if metric is None:
        return None
    node = _metric_nodes_by_metric_id(team_id, [metric.id]).get(metric.id)
    if node is None:
        return None
    return to_metric_dto(metric, node=node)


@transaction.atomic
def update_metric(params: contracts.UpdateMetricParams) -> contracts.CatalogMetricDTO | None:
    metric = CatalogMetric.objects.filter(team_id=params.team_id, id=params.metric_id).first()
    if metric is None:
        return None
    fields: list[str] = []
    if params.description is not None:
        metric.description = params.description
        fields.append("description")
    if params.definition is not None:
        metric.definition = params.definition
        fields.append("definition")
    if fields:
        metric.save(update_fields=[*fields, "updated_at"])
    node = _metric_nodes_by_metric_id(params.team_id, [metric.id]).get(metric.id)
    if node is None:
        return None
    return to_metric_dto(metric, node=node)


@transaction.atomic
def upsert_metric(params: contracts.UpsertMetricParams) -> contracts.CatalogMetricDTO:
    """Upsert a CatalogMetric and bind a CatalogNode(kind=metric) to it.

    Single atomic write — metric row and node row live or die together. Idempotent on
    (team, name) for the metric and (team, kind=metric, name) for the node; calling twice
    with the same name updates description, definition, and the node's reverse pointer
    without creating duplicates.
    """
    metric, _ = CatalogMetric.objects.update_or_create(
        team_id=params.team_id,
        name=params.name,
        defaults={
            "description": params.description,
            "definition": params.definition,
        },
    )
    node_defaults: dict = {
        "content_type": ContentType.objects.get_for_model(CatalogMetric),
        "object_id": metric.id,
        "last_traversed_at": timezone.now(),
    }
    if params.generator_model is not None:
        node_defaults["generator_model"] = params.generator_model
    if params.confidence is not None:
        node_defaults["confidence"] = params.confidence
    node, _ = CatalogNode.objects.update_or_create(
        team_id=params.team_id,
        kind=CatalogNode.Kind.METRIC,
        name=params.name,
        defaults=node_defaults,
    )
    return to_metric_dto(metric, node=node)


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
