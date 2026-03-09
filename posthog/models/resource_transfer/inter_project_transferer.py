from collections.abc import Generator, Iterable
from graphlib import TopologicalSorter
from typing import Any, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction

import structlog

from posthog.models import Project, Team, User
from posthog.models.resource_transfer.resource_transfer import ResourceTransfer
from posthog.models.resource_transfer.types import (
    ResourceKind,
    ResourceMap,
    ResourcePayload,
    ResourceTransferEdge,
    ResourceTransferKey,
    ResourceTransferVertex,
    RewriteRelationFn,
)
from posthog.models.resource_transfer.visitors import ResourceTransferVisitor

logger = structlog.get_logger(__name__)

MAX_RELATIONAL_RECURSION_DEPTH = 20


def duplicate_resource_to_new_team(
    resource: Any,
    team: Team,
    substitutions: list[tuple[ResourceTransferKey, ResourceTransferKey]] | None = None,
    *,
    created_by: User,
) -> list[Any]:
    """
    Duplicate a resource and any relations it depends on to another team.

    :param resource: The resource to start the duplication with.
    :param team: The team to copy the resource to.
    :param created_by: The user who initiated the transfer.

    :returns: A list of the newly created resources
    """
    source_team = resource.team
    logger.info(
        "resource_transfer.start",
        resource_type=type(resource).__name__,
        resource_pk=str(resource.pk),
        source_team_id=source_team.pk,
        destination_team_id=team.pk,
        created_by_id=created_by.pk,
        substitution_count=len(substitutions) if substitutions else 0,
    )
    with transaction.atomic():
        graph = list(build_resource_duplication_graph(resource, set()))
        logger.info(
            "resource_transfer.graph_built",
            vertex_count=len(graph),
            vertices=[{"key": (v.key[0], str(v.key[1])), "edge_count": len(v.edges)} for v in graph],
        )
        dag = dag_sort_duplication_graph(graph)
        logger.info(
            "resource_transfer.dag_sorted",
            dag_order=[(v.key[0], str(v.key[1])) for v in dag],
        )
        result = duplicate_resources_from_dag(
            dag, source_team, team, substitutions if substitutions is not None else [], created_by=created_by
        )
        logger.info(
            "resource_transfer.complete",
            resource_type=type(resource).__name__,
            resource_pk=str(resource.pk),
            duplicated_count=len(result),
        )
        return result


def duplicate_resources_from_dag(
    dag: Iterable[ResourceTransferVertex],
    source_team: Team,
    new_team: Team,
    substitutions: list[tuple[ResourceTransferKey, ResourceTransferKey]],
    *,
    created_by: User,
) -> list[Any]:
    """
    Given a DAG of vertices, execute the database operations to copy the resources described by each vertex into the new team.
    Also records a ResourceTransfer for each mutable resource that is created.

    :param dag: The DAG of vertices. Call `dag_sort_duplication_graph` to get this. Anything that isn't a DAG will likely result in a ValueError.
    :param source_team: The team the resources are being copied from.
    :param new_team: The team to copy the resources to.
    :param substitutions: A list of (source_key, destination_key) pairs representing substitutions to use.
    :param created_by: The user who initiated the transfer.

    :returns: A list of the newly created resources
    """
    consumed_vertices: ResourceMap = {}
    transfer_records: list[ResourceTransfer] = []
    mapped_substitutions = _get_mapped_substitutions(substitutions, target_team=new_team)

    logger.info(
        "resource_transfer.duplicate_dag.start",
        source_team_id=source_team.pk,
        destination_team_id=new_team.pk,
        substitution_count=len(mapped_substitutions),
        substitution_keys=[(f"{k[0]}:{k[1]}") for k in mapped_substitutions],
    )

    for vertex in dag:
        visitor = ResourceTransferVisitor.get_visitor(vertex.model)

        if visitor is None:
            logger.error(
                "resource_transfer.duplicate_dag.no_visitor",
                model=vertex.model.__name__,
                vertex_pk=str(vertex.primary_key),
            )
            raise TypeError(f"Cannot duplicate {vertex.model} because it has no configured visitor")

        if visitor.is_immutable():
            logger.info(
                "resource_transfer.duplicate_dag.immutable_passthrough",
                kind=visitor.kind,
                resource_pk=str(vertex.primary_key),
            )
            vertex.duplicated_resource = vertex.source_resource
            consumed_vertices[vertex.key] = vertex
            continue

        if (substitution := mapped_substitutions.get(vertex.key, None)) is not None:
            logger.info(
                "resource_transfer.duplicate_dag.substitution_applied",
                kind=visitor.kind,
                source_pk=str(vertex.primary_key),
                substituted_pk=str(substitution.pk),
            )
            vertex.duplicated_resource = substitution
        else:
            vertex.duplicated_resource = _duplicate_vertex(vertex, visitor, new_team, consumed_vertices)
            logger.info(
                "resource_transfer.duplicate_dag.vertex_duplicated",
                kind=visitor.kind,
                source_pk=str(vertex.primary_key),
                new_pk=str(vertex.duplicated_resource.pk) if vertex.duplicated_resource else None,
            )

        if vertex.duplicated_resource is None:
            logger.error(
                "resource_transfer.duplicate_dag.null_duplication",
                kind=visitor.kind,
                vertex_pk=str(vertex.primary_key),
            )
            raise ValueError("Resource should have been duplicated, but was null")

        consumed_vertices[vertex.key] = vertex

        if vertex.key not in mapped_substitutions:
            transfer_records.append(
                ResourceTransfer(
                    source_team=source_team,
                    destination_team=new_team,
                    created_by=created_by,
                    resource_kind=visitor.kind,
                    resource_id=str(vertex.source_resource.pk),
                    duplicated_resource_id=str(vertex.duplicated_resource.pk),
                )
            )

    ResourceTransfer.objects.bulk_create(transfer_records)
    logger.info(
        "resource_transfer.duplicate_dag.complete",
        transfer_records_created=len(transfer_records),
        total_vertices_consumed=len(consumed_vertices),
    )
    return [x.duplicated_resource for x in consumed_vertices.values()]


def dag_sort_duplication_graph(graph: Iterable[ResourceTransferVertex]) -> tuple[ResourceTransferVertex, ...]:
    """
    Creates a DAG from an iterable set of vertices.

    :param graph: An iterable set of vertices with edges.
    """
    mapped_graph = {x.key: x for x in graph}
    processed_graph = {k: {y.key for y in v.edges} for k, v in mapped_graph.items()}

    logger.info(
        "resource_transfer.dag_sort.adjacency",
        vertex_count=len(mapped_graph),
        adjacency={f"{k[0]}:{k[1]}": [f"{dep[0]}:{dep[1]}" for dep in deps] for k, deps in processed_graph.items()},
    )

    sorter = TopologicalSorter(processed_graph)
    dag_sorted_graph = sorter.static_order()

    result = tuple(mapped_graph[x] for x in dag_sorted_graph)

    logger.info(
        "resource_transfer.dag_sort.complete",
        sorted_order=[(v.key[0], str(v.key[1])) for v in result],
    )

    return result


def build_resource_duplication_graph(
    resource: Any, exclude_set: set[ResourceTransferKey], depth: int = 1
) -> Generator[ResourceTransferVertex, None, None]:
    """
    This function builds a graph representing the relations in the connected component that `resource` is a member of.

    Each vertex represents a database row. Each edge represents a relation from that row to another row in the database.

    Vertices are indexed by the tuple (resource's data model, resource's primary key).

    `resource` must be a member of a connected component that does not infinitely span the database. In practice, this means a
    ValueError will be raised if resource is a linked list with many entries.

    :param resource: The starting resource
    :param exclude_set: A set of vertices to exclude from the DFS search. You should probably just provide `[]` unless you know what you are doing.
    :param depth: The depth of the recursion. Used to limit recursion.
    """
    if depth > MAX_RELATIONAL_RECURSION_DEPTH:
        logger.error(
            "resource_transfer.graph.max_depth_exceeded",
            resource_type=type(resource).__name__,
            resource_pk=str(resource.pk),
            depth=depth,
        )
        raise ValueError("Encountered too many recursive relations while duplicating resource")

    visitor = ResourceTransferVisitor.get_visitor(resource)

    if visitor is None:
        logger.error(
            "resource_transfer.graph.no_visitor",
            resource_type=type(resource).__name__,
        )
        raise TypeError(f"Cannot visit {type(resource)}")

    model = visitor.get_model()

    if (visitor.kind, resource.pk) in exclude_set:
        logger.info(
            "resource_transfer.graph.skip_visited",
            kind=visitor.kind,
            resource_pk=str(resource.pk),
            depth=depth,
        )
        return

    exclude_set.add((visitor.kind, resource.pk))

    if visitor.is_immutable():
        logger.info(
            "resource_transfer.graph.immutable_vertex",
            kind=visitor.kind,
            resource_pk=str(resource.pk),
            depth=depth,
        )
        yield ResourceTransferVertex(model=model, primary_key=resource.pk, source_resource=resource, edges=[])
        return

    model = visitor.get_model()
    edges = visitor.get_dynamic_edges(resource)

    if edges:
        logger.info(
            "resource_transfer.graph.dynamic_edges",
            kind=visitor.kind,
            resource_pk=str(resource.pk),
            dynamic_edges=[
                {"name": e.name, "target_model": e.target_model.__name__, "target_pk": str(e.target_primary_key)}
                for e in edges
            ],
        )

    for edge in edges:
        try:
            related_resource = edge.target_model.objects.get(pk=edge.target_primary_key)
            yield from build_resource_duplication_graph(related_resource, exclude_set, depth + 1)
        except ObjectDoesNotExist:
            logger.exception(
                "resource_transfer.graph.dynamic_edge_missing",
                kind=visitor.kind,
                resource_pk=str(resource.pk),
                target_model=edge.target_model.__name__,
                target_pk=str(edge.target_primary_key),
            )
            raise ValueError(
                f"Could not fetch dynamic relationship {edge.target_model.__name__}:{edge.target_primary_key}"
            )

    for attribute_name, attribute_value in model.__dict__.items():
        if not visitor.should_touch_field(attribute_name) or not visitor.is_relation(attribute_name):
            continue

        if visitor.is_many_to_many_relation(attribute_name):
            manager = getattr(resource, attribute_name)

            through_filter = {manager.source_field.attname: resource.pk}
            through_resources = attribute_value.through.objects.filter(**through_filter).all()

            logger.info(
                "resource_transfer.graph.m2m_relation",
                kind=visitor.kind,
                resource_pk=str(resource.pk),
                attribute=attribute_name,
                through_model=attribute_value.through.__name__,
                through_count=through_resources.count(),
            )

            for through_resource in through_resources:
                yield from build_resource_duplication_graph(through_resource, exclude_set, depth + 1)
        else:
            related_model = attribute_value.field.related_model
            related_resource = getattr(resource, attribute_name)

            if related_resource is None:
                continue

            logger.info(
                "resource_transfer.graph.fk_relation",
                kind=visitor.kind,
                resource_pk=str(resource.pk),
                attribute=attribute_name,
                related_model=related_model.__name__,
                related_pk=str(related_resource.pk),
                depth=depth,
            )

            yield from build_resource_duplication_graph(related_resource, exclude_set, depth + 1)
            edges.append(
                ResourceTransferEdge(
                    name=attribute_name,
                    target_model=related_model,
                    target_primary_key=related_resource.pk,
                    rewrite_relation=_make_relation_rewriter(attribute_name, related_model, related_resource.pk),
                )
            )

    logger.info(
        "resource_transfer.graph.vertex_built",
        kind=visitor.kind,
        resource_pk=str(resource.pk),
        edge_count=len(edges),
        edges=[
            {"name": e.name, "target_model": e.target_model.__name__, "target_pk": str(e.target_primary_key)}
            for e in edges
        ],
        depth=depth,
    )
    yield ResourceTransferVertex(model=model, primary_key=resource.pk, source_resource=resource, edges=edges)


def _make_relation_rewriter(
    relation_name: str, related_model: type[models.Model], related_pk: Any
) -> RewriteRelationFn:
    def _rewrite_relation(payload: ResourcePayload, resource_map: ResourceMap) -> ResourcePayload:
        related_visitor = ResourceTransferVisitor.get_visitor(related_model)

        if related_visitor is None:
            logger.error(
                "resource_transfer.rewrite_relation.no_visitor",
                relation_name=relation_name,
                related_model=related_model.__name__,
            )
            raise TypeError(f"Model has no configured visitor: {related_model.__name__}")

        related_vertex = resource_map.get((related_visitor.kind, related_pk))

        if related_vertex is None:
            logger.error(
                "resource_transfer.rewrite_relation.missing_dependency",
                relation_name=relation_name,
                related_model=related_model.__name__,
                related_pk=str(related_pk),
                available_keys=[f"{k[0]}:{k[1]}" for k in resource_map],
            )
            raise ValueError(
                f"Could not duplicate relation of type {related_model.__name__}: attempted to reference relation before creation"
            )

        return {**payload, relation_name: related_vertex.duplicated_resource}

    return _rewrite_relation


def get_suggested_substitutions(
    dag: Iterable[ResourceTransferVertex], new_team: Team
) -> list[tuple[ResourceTransferKey, ResourceTransferKey]]:
    """
    Return a list of (source_key, destination_key) pairs representing suggested substitutions
    based on past transfers to the destination team.
    """
    recommendations: list[tuple[ResourceTransferKey, ResourceTransferKey]] = []

    for vertex in dag:
        visitor = ResourceTransferVisitor.get_visitor(vertex.model)

        if visitor is None:
            raise TypeError(f"Model has no configured visitor: {vertex.model.__name__}")

        if visitor.is_immutable():
            continue

        suggested_resource = _find_resource_with_transfer_record(visitor, vertex, new_team)

        if suggested_resource is None:
            suggested_resource = _find_resource_with_same_name(visitor, vertex, new_team)

        if suggested_resource is None:
            continue

        source_key: ResourceTransferKey = (visitor.kind, vertex.source_resource.pk)
        dest_key: ResourceTransferKey = (
            cast(ResourceKind, visitor.kind),
            suggested_resource.pk,
        )
        recommendations.append((source_key, dest_key))

    return recommendations


def _find_resource_with_transfer_record(
    visitor: type[ResourceTransferVisitor], vertex: ResourceTransferVertex, new_team: Team
) -> Any | None:
    transfer_record = (
        ResourceTransfer.objects.filter(
            resource_kind=visitor.kind,
            resource_id=str(vertex.source_resource.pk),
            destination_team=new_team,
        )
        .order_by("-last_transferred_at")
        .first()
    )

    if transfer_record is None:
        return None

    model = visitor.get_model()
    try:
        previously_duplicated_resource = model.objects.get(pk=transfer_record.duplicated_resource_id)

        return previously_duplicated_resource
    except ObjectDoesNotExist:
        return None


def _find_resource_with_same_name(
    visitor: type[ResourceTransferVisitor], vertex: ResourceTransferVertex, new_team: Team
) -> Any | None:
    model = visitor.get_model()

    resource = cast(Any, vertex.source_resource)

    if not hasattr(resource, "name") or not resource.name or not hasattr(resource, "team"):
        return None

    matching_resource = model.objects.filter(name=resource.name, team=new_team).first()

    return matching_resource


def _get_mapped_substitutions(
    substitutions: list[tuple[ResourceTransferKey, ResourceTransferKey]],
    target_team: Team | None = None,
) -> dict[ResourceTransferKey, Any]:
    """
    Build a mapping from source resource keys to destination resource instances.

    Each substitution is a pair of (source_key, destination_key) where:
    - source_key identifies the resource in the source team's DAG
    - destination_key identifies the existing resource in the destination team to use instead

    If target_team is provided, every destination resource is verified to belong to that team.
    """
    mapped_substitutions: dict[ResourceTransferKey, Any] = {}

    logger.info(
        "resource_transfer.map_substitutions.start",
        substitution_count=len(substitutions),
        target_team_id=target_team.pk if target_team else None,
    )

    for (source_kind, source_pk), (dest_kind, dest_pk) in substitutions:
        source_visitor = ResourceTransferVisitor.get_visitor(source_kind)
        if source_visitor is None:
            logger.error(
                "resource_transfer.map_substitutions.invalid_source_kind",
                source_kind=source_kind,
                source_pk=str(source_pk),
            )
            raise TypeError(f"Received invalid kind for substitution source: {source_kind}")

        dest_visitor = ResourceTransferVisitor.get_visitor(dest_kind)
        if dest_visitor is None:
            logger.error(
                "resource_transfer.map_substitutions.invalid_dest_kind",
                dest_kind=dest_kind,
                dest_pk=str(dest_pk),
            )
            raise TypeError(f"Received invalid kind for substitution destination: {dest_kind}")

        source_model = source_visitor.get_model()
        try:
            source_resource = source_model.objects.get(pk=source_pk)
        except ObjectDoesNotExist:
            logger.exception(
                "resource_transfer.map_substitutions.source_not_found",
                source_kind=source_kind,
                source_pk=str(source_pk),
            )
            raise ValueError(f"Could not find source resource: {source_kind} {source_pk}")

        dest_model = dest_visitor.get_model()
        try:
            dest_resource = dest_model.objects.get(pk=dest_pk)
        except ObjectDoesNotExist:
            logger.exception(
                "resource_transfer.map_substitutions.dest_not_found",
                dest_kind=dest_kind,
                dest_pk=str(dest_pk),
            )
            raise ValueError(f"Could not find substituted resource: {dest_kind} {dest_pk}")

        if target_team is not None:
            resource_team = dest_visitor.get_resource_team(dest_resource)
            if resource_team.pk != target_team.pk:
                logger.warning(
                    "resource_transfer.map_substitutions.team_mismatch",
                    dest_kind=dest_kind,
                    dest_pk=str(dest_pk),
                    resource_team_id=resource_team.pk,
                    target_team_id=target_team.pk,
                )
                raise ValueError(
                    f"Substitution resource {dest_kind} {dest_pk} belongs to team {resource_team.pk}, "
                    f"not destination team {target_team.pk}"
                )

        normalized_key: ResourceTransferKey = (source_kind, source_resource.pk)
        mapped_substitutions[normalized_key] = dest_resource

        logger.info(
            "resource_transfer.map_substitutions.mapped",
            source_kind=source_kind,
            source_pk=str(source_resource.pk),
            dest_kind=dest_kind,
            dest_pk=str(dest_resource.pk),
        )

    return mapped_substitutions


def _duplicate_vertex(
    vertex: ResourceTransferVertex,
    visitor: type[ResourceTransferVisitor],
    new_team: Team,
    consumed_vertices: dict[ResourceTransferKey, ResourceTransferVertex],
) -> Any:
    payload = {}
    primitive_fields: list[str] = []

    for attribute_name, attribute_value in vertex.source_resource.__dict__.items():
        if not visitor.should_touch_field(attribute_name) or visitor.is_relation(attribute_name):
            continue

        payload[attribute_name] = attribute_value
        primitive_fields.append(attribute_name)

    logger.info(
        "resource_transfer.duplicate_vertex.primitives",
        kind=visitor.kind,
        source_pk=str(vertex.primary_key),
        primitive_fields=primitive_fields,
    )

    for edge in vertex.edges:
        if edge.target_model is Team:
            payload[edge.name] = new_team
            logger.info(
                "resource_transfer.duplicate_vertex.rewrite_team",
                kind=visitor.kind,
                source_pk=str(vertex.primary_key),
                edge_name=edge.name,
                new_team_id=new_team.pk,
            )
        elif edge.target_model is Project:
            payload[edge.name] = new_team.project
            logger.info(
                "resource_transfer.duplicate_vertex.rewrite_project",
                kind=visitor.kind,
                source_pk=str(vertex.primary_key),
                edge_name=edge.name,
                new_project_id=new_team.project.pk,
            )
        else:
            payload = edge.rewrite_relation(payload, consumed_vertices)
            logger.info(
                "resource_transfer.duplicate_vertex.rewrite_relation",
                kind=visitor.kind,
                source_pk=str(vertex.primary_key),
                edge_name=edge.name,
                target_model=edge.target_model.__name__,
                target_pk=str(edge.target_primary_key),
            )

    new_resource = visitor.get_model().objects.create(**payload)
    logger.info(
        "resource_transfer.duplicate_vertex.created",
        kind=visitor.kind,
        source_pk=str(vertex.primary_key),
        new_pk=str(new_resource.pk),
        model=visitor.get_model().__name__,
    )
    return new_resource
