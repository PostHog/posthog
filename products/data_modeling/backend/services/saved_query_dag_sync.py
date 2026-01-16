import uuid
from typing import TYPE_CHECKING

from django.utils import timezone

import structlog
from posthoganalytics import capture_exception

from posthog.hogql.database.database import Database
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError

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
    Resolve a dependency name to a Node, creating TABLE nodes as needed.

    Resolution order (same as get_or_create_query_parent_paths in modeling.py):
    1. Check if it's a SavedQuery name -> return existing VIEW/MATVIEW node
    2. Check if it's a DataWarehouseTable -> return/create TABLE node
    3. Check if it's a PostHog table (events, persons, etc.) -> return/create TABLE node
    4. Raise UnknownParentError if not found
    """
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery

    # 1. saved query
    try:
        saved_query = (
            DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(team=team, name=dependency_name).get()
        )
        # get or create node
        node_type = NodeType.MAT_VIEW if saved_query.is_materialized else NodeType.VIEW
        node, _ = Node.objects.get_or_create(
            team=team, dag_id=dag_id, name=dependency_name, saved_query=saved_query, type=node_type
        )
        return node
    except DataWarehouseSavedQuery.DoesNotExist:
        pass
    # 2. warehouse source table
    try:
        table = database.get_table(dependency_name)
        if isinstance(table, HogQLDataWarehouseTable):
            if table.table_id:
                warehouse_table = (
                    DataWarehouseTable.objects.exclude(deleted=True).filter(team=team, id=table.table_id).get()
                )
            else:
                warehouse_table = (
                    DataWarehouseTable.objects.exclude(deleted=True).filter(team=team, name=table.name).get()
                )
            node, _ = Node.objects.get_or_create(
                team=team,
                dag_id=dag_id,
                name=dependency_name,
                type=NodeType.TABLE,
                properties={"origin": "warehouse", "warehouse_table_id": str(warehouse_table.id)},
            )
            return node
    except (DataWarehouseTable.DoesNotExist, QueryError):
        pass
    # 3. posthog system table
    try:
        database.get_table(dependency_name)
        # if we haven't returned or errored by this point, this is a posthog system table
        node, _ = Node.objects.get_or_create(
            team=team, dag_id=dag_id, name=dependency_name, type=NodeType.TABLE, properties={"origin": "posthog"}
        )
        return node
    except QueryError:
        pass
    # 4. unknown parent
    raise UnknownParentError(dependency_name, "")


def sync_saved_query_to_dag(saved_query: "DataWarehouseSavedQuery") -> Node | None:
    """
    Create or update Node and Edges for a SavedQuery.

    1. Validate and parse the query to extract dependencies
    2. Get or create the Node for this SavedQuery
    3. Resolve each dependency to a Node (creating TABLE nodes for sources)
    4. Delete existing incoming edges (dependencies may have changed)
    5. Create new edges, catching cycle errors and creating conflict edges

    Returns the Node for the SavedQuery, or None if query parsing fails.
    """
    team = saved_query.team
    dag_id = get_dag_id(team.id)
    # parse query first - if this fails, we don't create/update the node
    query = saved_query.query.get("query")
    if not query:
        raise ValueError(f"DataWarehouseSavedQuery has no query: saved_query_id={saved_query.id}")
    try:
        dependencies = get_parents_from_model_query(query)
    except Exception as e:
        logger.warning("Failed to parse query for dependencies", saved_query_id=str(saved_query.id), error=str(e))
        capture_exception(e)
        return None
    # determine node type based on materialization status (fk to datawarehouse table)
    node_type = NodeType.MAT_VIEW if saved_query.table else NodeType.VIEW
    target, _ = Node.objects.get_or_create(
        saved_query=saved_query,
        team=team,
        dag_id=dag_id,
        defaults={"name": saved_query.name, "type": node_type},
    )
    # update type (name is automatically synced from saved_query in Node.save())
    target.type = node_type

    database = Database.create_for(team=team)
    # clear previous incoming edges, dependencies may have changed
    Edge.objects.filter(target=target).delete()

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
    target.properties = {**target.properties, "unresolved_dependencies": unresolved}
    # name is included in update_fields because Node.save() auto-syncs it from saved_query
    target.save(update_fields=["name", "type", "properties"])
    return target


def delete_node_from_dag(saved_query: "DataWarehouseSavedQuery") -> None:
    """
    Delete the Node for a SavedQuery (cascades to Edges via on_delete=CASCADE).

    Must be called BEFORE soft_delete() due to on_delete=PROTECT on the saved_query FK.
    """
    Node.objects.filter(saved_query=saved_query).delete()


def update_node_type(saved_query: "DataWarehouseSavedQuery", type: NodeType) -> None:
    """Update a Node's type to MAT_VIEW when materialized."""
    Node.objects.filter(saved_query=saved_query).update(type=type)
