# V2 - focus on using iterators to abstract object creation from iteration, also better understanding of django internals

from collections.abc import Generator, Iterable
from dataclasses import dataclass
from graphlib import TopologicalSorter
from typing import Any

from django.db import models, transaction

from posthog.models import Project, Team
from posthog.models.resource_transfer.visitors import ResourceTransferVisitor

MAX_RELATIONAL_RECURSION_DEPTH = 20


@dataclass
class ResourceTransferEdge:
    name: str
    source_model: type
    source_primary_key: Any
    target_model: type
    target_primary_key: Any

    @property
    def key(self) -> tuple[type, Any]:
        return (self.target_model, self.target_primary_key)


@dataclass
class ResourceTransferVertex:
    model: type
    primary_key: Any
    source_resource: models.Model
    edges: list[ResourceTransferEdge]
    duplicated_resource: models.Model | None = None

    @property
    def key(self) -> tuple[type, Any]:
        return (self.model, self.primary_key)


def duplicate_resource_to_new_team(resource: Any, team: Team) -> list[Any]:
    """
    Duplicate a resource and any relations it depends on to another team.

    :param resource: The resource to start the duplication with.
    :param team: The team to copy the resource to.

    :returns: A list of the newly created resources
    """
    with transaction.atomic():
        graph = build_resource_duplication_graph(resource, set())
        dag = dag_sort_duplication_graph(graph)
        return duplicate_resources_from_dag(dag, team)


def duplicate_resources_from_dag(dag: Iterable[ResourceTransferVertex], new_team: Team) -> list[Any]:
    """
    Given a DAG of vertices, execute the database operations to copy the resources described by each vertex into the new team.

    :param dag: The DAG of vertices. Call `dag_sort_duplication_graph` to get this. Anything that isn't a DAG will likely result in a ValueError.
    :param new_team: The team to copy the resources to.
    """
    consumed_vertices: dict[tuple[type, Any], ResourceTransferVertex] = {}

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
            print(f"{edge.source_model.__name__}.{edge.name} -> {edge.target_model.__name__}")
            if edge.target_model is Team:
                print(f"{vertex.model.__name__}.{edge.name} is Team relation")
                payload[edge.name] = new_team
            elif edge.target_model is Project:
                print(f"{vertex.model.__name__}.{edge.name} is Project relation")
                payload[edge.name] = new_team.project
            else:
                print(f"{vertex.model.__name__}.{edge.name} is miscellaneous relation ({edge.target_model.__name__})")
                related_vertex = consumed_vertices.get(edge.key, None)
                if related_vertex is None:
                    raise ValueError(
                        f"Could not duplicate {vertex.model}: attempted to instantiate relation before it was created in DAG"
                    )

                payload[edge.name] = related_vertex.duplicated_resource

        # yolo
        print(f"YOLO-ing resource create: {payload}")
        vertex.duplicated_resource = visitor.get_model().objects.create(**payload)

        consumed_vertices[vertex.key] = vertex

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
    resource: Any, exclude_set: set[tuple[type, Any]], depth: int = 1
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
    edges = []

    # NOTE: in some cases there are "hidden" relations, such as Insights referencing actions or cohorts. This will need to be updated in future to handle this
    # Reece note: this should probably be a classmethod in the Visitor implementation for the model that takes in the runtime resource object, and spits out any extra edges
    for attribute_name, attribute_value in model.__dict__.items():
        if not visitor.should_touch_field(attribute_name) or not visitor.is_relation(attribute_name):
            continue

        if visitor.is_many_to_many_relation(attribute_name):
            # need to recurse on the through relation, because the through relation contains the foreign keys we need for the dependency graph
            descriptor = getattr(resource, attribute_name)
            for related_resource in descriptor.all():
                through_model = attribute_value.through
                through_filter = {
                    descriptor.source_field.attname: resource.pk,
                    descriptor.target_field.attname: related_resource.pk,
                }
                through_resource = through_model.objects.filter(**through_filter).first()

                if through_resource is None:
                    continue

                print(f"{type(resource).__name__}.{attribute_name} -> {through_model.__name__} ({through_resource.pk})")
                yield from build_resource_duplication_graph(through_resource, exclude_set, depth + 1)
        else:
            related_model = attribute_value.field.related_model
            related_resource = getattr(resource, attribute_name)

            if related_resource is None:
                continue

            print(f"{type(resource).__name__}.{attribute_name} -> {related_model.__name__} ({related_resource.pk})")
            yield from build_resource_duplication_graph(related_resource, exclude_set, depth + 1)
            edges.append(
                ResourceTransferEdge(
                    name=attribute_name,
                    source_model=model,
                    source_primary_key=resource.pk,
                    target_model=related_model,
                    target_primary_key=related_resource.pk,
                )
            )

    yield ResourceTransferVertex(model=model, primary_key=resource.pk, source_resource=resource, edges=edges)
