import uuid
from typing import TYPE_CHECKING

from django.utils import timezone

import structlog

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery as HogQLSavedQuery
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.models.edge import CycleDetectionError, Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_warehouse.backend.models.modeling import UnknownParentError, get_parents_from_model_query
from products.data_warehouse.backend.models.table import DataWarehouseTable

if TYPE_CHECKING:
    from posthog.models import Team

    from products.data_warehouse.backend.models import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def get_dag_id(team_id: int) -> str:
    """Return the standard dag_id for a team."""
    return f"posthog_{team_id}"


def get_conflict_dag_id(team_id: int) -> str:
    """Return a unique conflict dag_id for DLQ edges or nodes."""
    return f"conflict_{uuid.uuid4().hex[:8]}_{get_dag_id(team_id)}"


def resolve_dependency_to_node(
    dependency_name: str,
    team: "Team",
    dag_id: str,
    database: Database,
) -> Node:
    """
    Resolve a dependency name to a Node following HogQL's resolution priority.

    Creates TABLE nodes as needed for warehouse and PostHog system tables.
    For SavedQuery views and matviews, we only find existing nodes or error.

    Resolution order:
    1. PostHog system table (events, persons, etc.)
    2. SavedQuery view or matview
    3. DataWarehouse table (postgres, stripe, etc.)

    Raises UnknownParentError if the dependency cannot be resolved.
    """
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery

    # get hogql's understanding of this table
    try:
        table = database.get_table(dependency_name)
    except QueryError:
        raise UnknownParentError(dependency_name, "")
    # ephemeral view
    if isinstance(table, HogQLSavedQuery):
        saved_query = DataWarehouseSavedQuery.objects.get(team=team, name=dependency_name, deleted=False)
        return Node.objects.get(team=team, dag_id=dag_id, saved_query=saved_query, name=dependency_name)

    # table in s3
    if isinstance(table, HogQLDataWarehouseTable):
        if table.table_id:
            matview_saved_query = (
                DataWarehouseSavedQuery.objects.filter(team=team, table_id=table.table_id).exclude(deleted=True).first()
            )
            # matview
            if matview_saved_query is not None:
                return Node.objects.get(team=team, dag_id=dag_id, saved_query=matview_saved_query, name=dependency_name)
            # warehouse table
            warehouse_table = (
                DataWarehouseTable.objects.filter(team=team, id=table.table_id).exclude(deleted=True).first()
            )
        else:
            warehouse_table = (
                DataWarehouseTable.objects.filter(team=team, name=dependency_name).exclude(deleted=True).first()
            )
        if not warehouse_table:
            raise UnknownParentError(dependency_name, "")
        node, _ = Node.objects.get_or_create(
            team=team,
            dag_id=dag_id,
            name=dependency_name,
            type=NodeType.TABLE,
            defaults={"properties": {"origin": "warehouse", "warehouse_table_id": str(warehouse_table.id)}},
        )
        return node
    # system table
    node, _ = Node.objects.get_or_create(
        team=team,
        dag_id=dag_id,
        name=dependency_name,
        type=NodeType.TABLE,
        defaults={"properties": {"origin": "posthog"}},
    )
    return node


def sync_saved_query_to_dag(
    saved_query: "DataWarehouseSavedQuery",
    extra_properties: dict | None = None,  # TODO(andrew): remove this after backfill
) -> Node | None:
    """
    Create or update Node and Edges for a SavedQuery.

    1. Validate and parse the query to extract dependencies
    2. Get or create the Node for this SavedQuery
    3. Resolve each dependency to a Node (creating TABLE nodes for sources)
    4. Delete existing incoming edges (dependencies may have changed)
    5. Create new edges, catching cycle errors and creating conflict edges

    Args:
        saved_query: The SavedQuery to sync to the DAG
        extra_properties: Optional dict of properties to merge into created nodes and edges

    Returns the Node for the SavedQuery, or None if query parsing fails.
    """
    extra_properties = extra_properties or {}
    team = saved_query.team
    dag_id = get_dag_id(team.id)
    model_query = saved_query.query.get("query") if saved_query.query else None
    if not model_query:
        raise ValueError(f"DataWarehouseSavedQuery has no query: saved_query_id={saved_query.id}")

    # determine node type based on materialization status (fk to datawarehouse table)
    node_type = NodeType.MAT_VIEW if saved_query.table else NodeType.VIEW
    target, _ = Node.objects.get_or_create(
        team=team,
        saved_query=saved_query,
        dag_id=dag_id,
        defaults={"name": saved_query.name, "type": node_type, "properties": extra_properties},
    )
    # update type (name is automatically synced from saved_query in Node.save())
    target.type = node_type

    database = Database.create_for(team=team)
    # clear previous incoming edges, dependencies may have changed
    Edge.objects.filter(team=team, target=target).delete()

    # parse query to extract dependencies
    try:
        model_name = saved_query.name
        dependencies = get_parents_from_model_query(team, model_name, model_query)
    except QueryError as e:
        error_message = str(e)
        # handle circular dependency as a conflict edge
        if "circular dependency detected" in error_message.lower():
            logger.warning(
                "Cycle detected when parsing query",
                saved_query_id=saved_query.id,
                saved_query=saved_query.name,
                error=error_message,
            )
            conflict_dag_id = get_conflict_dag_id(team.id)
            # update the node to use conflict dag_id and store error info
            target.dag_id = conflict_dag_id
            target.properties = {
                **target.properties,
                **extra_properties,
                "error_type": "cycle",
                "error_message": error_message,
                "original_dag_id": dag_id,
                "detected_at": timezone.now().isoformat(),
            }
            target.save()
            # create conflict edge
            Edge(
                team=team,
                dag_id=conflict_dag_id,
                source=target,
                target=target,
                properties={
                    **extra_properties,
                    "error_type": "cycle",
                    "error_message": error_message,
                    "original_dag_id": dag_id,
                    "detected_at": timezone.now().isoformat(),
                },
            ).save(skip_validation=True)
            return target
        # other query errors should surface to the user
        target.delete()
        raise
    except Exception as e:
        target.delete()
        logger.warning("Failed to parse query for dependencies", saved_query_id=str(saved_query.id), error=str(e))
        capture_exception(e)
        return None

    unresolved = []
    for dependency_name in dependencies:
        try:
            source = resolve_dependency_to_node(dependency_name, team, dag_id, database)
            try:
                Edge.objects.create(
                    team=team,
                    dag_id=dag_id,
                    source=source,
                    target=target,
                    properties=extra_properties,
                )
            # dag mismatch error can't happen because we control the only dag id for now
            except CycleDetectionError as e:
                logger.warning(
                    "Cycle detected when creating edge",
                    source=dependency_name,
                    target=saved_query.name,
                    error=str(e),
                )
                # creates the edge without validation for DLQ purposes
                Edge(
                    team=team,
                    dag_id=get_conflict_dag_id(team.id),
                    source=source,
                    target=target,
                    properties={
                        **extra_properties,
                        "error_type": "cycle",
                        "error_message": str(e),
                        "original_dag_id": dag_id,
                        "detected_at": timezone.now().isoformat(),
                    },
                ).save(skip_validation=True)
        except UnknownParentError:
            # source doesn't exist - this should fail at query parse time but just in case we save it on the props
            logger.warning(
                "Unknown parent for saved query",
                parent=dependency_name,
                saved_query=saved_query.name,
            )
            unresolved.append(
                {
                    "name": dependency_name,
                    "detected_at": timezone.now().isoformat(),
                }
            )
    # already includes extra properties from above
    target.properties = {**target.properties, "unresolved_dependencies": unresolved}
    # name is included in update_fields because Node.save() auto-syncs it from saved_query
    target.save(update_fields=["name", "type", "properties"])
    return target


class HasDependentsError(Exception):
    """Raised when attempting to delete a saved query that has dependents."""

    pass


def get_dependent_saved_queries(saved_query: "DataWarehouseSavedQuery") -> list["DataWarehouseSavedQuery"]:
    """
    Get SavedQueries that depend on this one (immediate dependents only).

    Returns a list of DataWarehouseSavedQuery objects that have edges pointing
    from this saved query's node (i.e., they reference this view in their query).
    """
    node = Node.objects.filter(team=saved_query.team, saved_query=saved_query).first()
    if not node:
        return []
    deps = Node.objects.filter(
        team=saved_query.team,
        incoming_edges__source=node,
        saved_query__isnull=False,
    ).select_related("saved_query")
    return [d.saved_query for d in deps if d.saved_query and not d.saved_query.deleted]


def delete_node_from_dag(saved_query: "DataWarehouseSavedQuery") -> None:
    """
    Delete the Node for a SavedQuery (cascades to edges)

    Must be called BEFORE soft_delete() due to on_delete=PROTECT on the saved_query FK.
    """
    deps = get_dependent_saved_queries(saved_query)
    if deps:
        raise HasDependentsError("Node cannot be deleted because it has dependents")
    Node.objects.filter(team=saved_query.team, saved_query=saved_query).delete()


def update_node_type(saved_query: "DataWarehouseSavedQuery", type: NodeType) -> None:
    """Update a Node's type to MAT_VIEW when materialized."""
    Node.objects.filter(team=saved_query.team, saved_query=saved_query).update(type=type)
