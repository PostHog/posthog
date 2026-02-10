from collections.abc import Generator, Iterable
from graphlib import TopologicalSorter
from typing import Any

from django.db import models, transaction

from posthog.models import Project, Team
from posthog.models.resource_transfer.resource_transfer import ResourceTransfer
from posthog.models.resource_transfer.types import (
    ResourceTransferEdge,
    ResourceTransferKey,
    ResourceTransferVertex,
    RewriteRelationFn,
)
from posthog.models.resource_transfer.visitors import ResourceTransferVisitor

MAX_RELATIONAL_RECURSION_DEPTH = 20


def duplicate_resource_to_new_team(resource: Any, team: Team) -> list[Any]:
    """
    Duplicate a resource and any relations it depends on to another team.

    :param resource: The resource to start the duplication with.
    :param team: The team to copy the resource to.

    :returns: A list of the newly created resources
    """
    source_team = resource.team
    with transaction.atomic():
        graph = list(build_resource_duplication_graph(resource, set()))
        dag = dag_sort_duplication_graph(graph)
        return duplicate_resources_from_dag(dag, source_team, team)


def duplicate_resources_from_dag(dag: Iterable[ResourceTransferVertex], source_team: Team, new_team: Team) -> list[Any]:
    """
    Given a DAG of vertices, execute the database operations to copy the resources described by each vertex into the new team.
    Also records a ResourceTransfer for each mutable resource that is created.

    :param dag: The DAG of vertices. Call `dag_sort_duplication_graph` to get this. Anything that isn't a DAG will likely result in a ValueError.
    :param source_team: The team the resources are being copied from.
    :param new_team: The team to copy the resources to.
    """
    consumed_vertices: dict[ResourceTransferKey, ResourceTransferVertex] = {}
    transfer_records: list[ResourceTransfer] = []

    for vertex in dag:
        payload = {}
        visitor = ResourceTransferVisitor.get_visitor(vertex.model)

        if visitor is None:
            raise TypeError(f"Cannot duplicate {vertex.model} because it has no configured visitor")

        if visitor.is_immutable():
            vertex.duplicated_resource = vertex.source_resource
            consumed_vertices[vertex.key] = vertex
            continue

        # handle primitives
        for attribute_name, attribute_value in vertex.source_resource.__dict__.items():
            if not visitor.should_touch_field(attribute_name) or visitor.is_relation(attribute_name):
                continue

            # anything past this point must be a non-relational column that we can safely copy
            payload[attribute_name] = attribute_value

        # handle relations
        for edge in vertex.edges:
            if edge.target_model is Team:
                payload[edge.name] = new_team
            elif edge.target_model is Project:
                payload[edge.name] = new_team.project
            else:
                payload = edge.rewrite_relation(payload, consumed_vertices)

        vertex.duplicated_resource = visitor.get_model().objects.create(**payload)
        consumed_vertices[vertex.key] = vertex

        transfer_records.append(
            ResourceTransfer(
                source_team=source_team,
                destination_team=new_team,
                resource_kind=visitor.kind,
                resource_id=str(vertex.duplicated_resource.pk),
            )
        )

    ResourceTransfer.objects.bulk_create(transfer_records)
    return [x.duplicated_resource for x in consumed_vertices.values()]


def dag_sort_duplication_graph(graph: Iterable[ResourceTransferVertex]) -> tuple[ResourceTransferVertex, ...]:
    """
    Creates a DAG from an iterable set of vertices.

    :param graph: An iterable set of vertices with edges.
    """
    # dag sort the graph
    mapped_graph = {x.key: x for x in graph}
    processed_graph = {k: {y.key for y in v.edges} for k, v in mapped_graph.items()}
    sorter = TopologicalSorter(processed_graph)
    dag_sorted_graph = sorter.static_order()

    return tuple(mapped_graph[x] for x in dag_sorted_graph)


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
        raise ValueError("Encountered too many recursive relations while duplicating resource")

    visitor = ResourceTransferVisitor.get_visitor(resource)

    if visitor is None:
        raise TypeError(f"Cannot visit {type(resource)}")

    model = visitor.get_model()

    if (model, resource.pk) in exclude_set:
        return

    exclude_set.add((model, resource.pk))

    if visitor.is_immutable():
        # this is a model that we never ever ever want to copy so we won't recurse on it
        yield ResourceTransferVertex(model=model, primary_key=resource.pk, source_resource=resource, edges=[])
        return

    model = visitor.get_model()
    edges = visitor.get_dynamic_edges(resource)

    for edge in edges:
        related_resource = edge.target_model.objects.get(pk=edge.target_primary_key)

        if related_resource is None:
            raise ValueError(
                f"Could not fetch dynamic relationship {edge.target_model.__name__}:{edge.target_primary_key}"
            )

        yield from build_resource_duplication_graph(related_resource, exclude_set, depth + 1)

    for attribute_name, attribute_value in model.__dict__.items():
        if not visitor.should_touch_field(attribute_name) or not visitor.is_relation(attribute_name):
            continue

        if visitor.is_many_to_many_relation(attribute_name):
            # need to recurse on the through relation, because the through relation contains the foreign keys we need for the dependency graph
            manager = getattr(resource, attribute_name)

            through_filter = {manager.source_field.attname: resource.pk}
            through_resources = attribute_value.through.objects.filter(**through_filter).all()

            for through_resource in through_resources:
                yield from build_resource_duplication_graph(through_resource, exclude_set, depth + 1)
        else:
            related_model = attribute_value.field.related_model
            related_resource = getattr(resource, attribute_name)

            if related_resource is None:
                continue

            yield from build_resource_duplication_graph(related_resource, exclude_set, depth + 1)
            edges.append(
                ResourceTransferEdge(
                    name=attribute_name,
                    target_model=related_model,
                    target_primary_key=related_resource.pk,
                    rewrite_relation=_make_relation_rewriter(attribute_name, related_model, related_resource.pk),
                )
            )

    yield ResourceTransferVertex(model=model, primary_key=resource.pk, source_resource=resource, edges=edges)


def _make_relation_rewriter(
    relation_name: str, related_model: type[models.Model], related_pk: Any
) -> RewriteRelationFn:
    def _rewrite_relation(
        payload: dict[str, Any], resource_map: dict[ResourceTransferKey, ResourceTransferVertex]
    ) -> dict[str, Any]:
        related_vertex = resource_map.get((related_model, related_pk))

        if related_vertex is None:
            raise ValueError(
                f"Could not duplicate relation of type {related_model.__name__}: attempted to reference relation before creation"
            )

        return {**payload, relation_name: related_vertex.duplicated_resource}

    return _rewrite_relation
