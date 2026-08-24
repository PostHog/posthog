from typing import TYPE_CHECKING, TypedDict

from django.db.models import QuerySet

import structlog

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery as HogQLSavedQuery
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError

from products.data_modeling.backend.logic.node_suspension import clear_suspension_if_query_changed
from products.data_modeling.backend.logic.schedule_reconcile import maybe_reconcile_dag
from products.data_modeling.backend.models.dag import DAG, REVENUE_ANALYTICS_DAG_NAME
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.modeling import UnknownParentError, get_parents_from_model_query
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

if TYPE_CHECKING:
    from posthog.models import Team

    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)

# properties["system"] marker set by consolidate_dags --adopt-unresolvable when a query's SQL
# would not resolve and its node was created without edges. A successful sync clears it.
DEGRADED_SYNC_KEY = "degraded_sync"


class DegradedSyncMarker(TypedDict):
    error: str
    at: str


def node_type_for(saved_query: "DataWarehouseSavedQuery") -> NodeType:
    """The node type a saved query's DAG node should carry."""
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        return NodeType.ENDPOINT
    if saved_query.table_id is not None:
        return NodeType.MAT_VIEW
    return NodeType.VIEW


def get_dag_id(team_id: int) -> str:
    """Return the standard dag_id for a team."""
    return f"posthog_{team_id}"


def _managed_cross_dag_reference(
    team: "Team", dag: DAG, dependency_name: str, saved_query: "DataWarehouseSavedQuery"
) -> Node | None:
    """A table node in `dag` standing in for a saved-query parent whose node lives in a managed
    DAG (Revenue Analytics). Cross-dag edges are forbidden, so a same-dag reference is the only
    join available. Returns None when the parent is not in a managed DAG, so the caller resolves
    normally and a user's own extra DAG stays a loud failure rather than a silent orphan."""
    if not Node.objects.filter(team=team, saved_query=saved_query, dag__name=REVENUE_ANALYTICS_DAG_NAME).exists():
        return None
    node, _ = Node.objects.get_or_create(
        team=team,
        dag=dag,
        name=dependency_name,
        type=NodeType.TABLE,
        defaults={"properties": {"origin": "cross_dag_view", "saved_query_id": str(saved_query.id)}},
    )
    return node


def resolve_dependency_to_node(
    dependency_name: str,
    team: "Team",
    database: Database,
    dag: DAG,
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
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    # get hogql's understanding of this table
    try:
        table = database.get_table(dependency_name)
    except QueryError:
        raise UnknownParentError(dependency_name, "")
    # ephemeral view
    if isinstance(table, HogQLSavedQuery):
        saved_query = DataWarehouseSavedQuery.objects.get(team=team, name=dependency_name, deleted=False)
        node = Node.objects.filter(team=team, dag=dag, saved_query=saved_query).first()
        if node is not None:
            return node
        reference = _managed_cross_dag_reference(team, dag, dependency_name, saved_query)
        if reference is not None:
            return reference
        return Node.objects.get(team=team, dag=dag, saved_query=saved_query, name=dependency_name)

    # table in s3
    if isinstance(table, HogQLDataWarehouseTable):
        if table.table_id:
            matview_saved_query = (
                DataWarehouseSavedQuery.objects.filter(team=team, table_id=table.table_id).exclude(deleted=True).first()
            )
            # matview
            if matview_saved_query is not None:
                node = Node.objects.filter(team=team, dag=dag, saved_query=matview_saved_query).first()
                if node is not None:
                    return node
                reference = _managed_cross_dag_reference(team, dag, dependency_name, matview_saved_query)
                if reference is not None:
                    return reference
                return Node.objects.get(team=team, dag=dag, saved_query=matview_saved_query, name=dependency_name)
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
            dag=dag,
            name=dependency_name,
            type=NodeType.TABLE,
            defaults={
                "properties": {"origin": "warehouse", "warehouse_table_id": str(warehouse_table.id)},
            },
        )
        return node
    # system table
    node, _ = Node.objects.get_or_create(
        team=team,
        dag=dag,
        name=dependency_name,
        type=NodeType.TABLE,
        defaults={"properties": {"origin": "posthog"}},
    )
    return node


class ManagedDAGError(Exception):
    """Raised when a user-initiated sync targets a system-managed DAG (e.g. Revenue Analytics)."""

    pass


def sync_saved_query_to_dag(
    saved_query: "DataWarehouseSavedQuery",
    extra_properties: dict | None = None,  # TODO(andrew): remove this after backfill
    dag: DAG | None = None,
    allow_managed: bool = False,
    reconcile: bool = True,
    database: Database | None = None,
) -> Node | None:
    """
    Create or update Node and Edges for a SavedQuery.

    1. Validate and parse the query to extract dependencies
    2. Get or create the Node for this SavedQuery
    3. Resolve each dependency to a Node (creating TABLE nodes for sources)
    4. Delete existing incoming edges (dependencies may have changed)
    5. Create new edges for each dependency

    Args:
        saved_query: The SavedQuery to sync to the DAG
        extra_properties: Optional dict of properties to merge into created nodes and edges
        dag: Optional DAG to use. If not provided, uses the default team DAG.
        allow_managed: Whether placement into a system-managed DAG is permitted. Only the
            internal managed-viewset sync passes this; user-initiated callers must not, so a
            same-team user can't insert nodes/edges into a managed DAG via the saved-query API.
        database: An optional prebuilt database to reuse for dependency resolution.

    Returns the Node for the SavedQuery, or None if query parsing fails.
    Raises QueryError or CycleDetectionError if the query would create an invalid DAG.
    Raises ManagedDAGError if dag is system-managed and allow_managed is False.
    """

    extra_properties = extra_properties or {}
    team = saved_query.team
    if dag is None:
        dag = DAG.get_or_create_default(team)
    if dag.is_managed and not allow_managed:
        raise ManagedDAGError(f"Cannot sync saved query into system-managed DAG: dag_id={dag.id}")
    model_query = saved_query.query.get("query") if saved_query.query else None
    if not model_query:
        raise ValueError(f"DataWarehouseSavedQuery has no query: saved_query_id={saved_query.id}")

    node_type = node_type_for(saved_query)

    target, _ = Node.objects.get_or_create(
        team=team,
        saved_query=saved_query,
        dag=dag,
        defaults={"name": saved_query.name, "type": node_type, "properties": extra_properties},
    )
    # update type (name is automatically synced from saved_query in Node.save())
    target.type = node_type

    # Internal DAG sync (no user); bypass warehouse HogQL access control so dependency resolution
    # sees every referenced table/view.
    if database is None:
        database = Database.create_for(team=team, bypass_warehouse_access_control=True)
    # clear previous incoming edges, dependencies may have changed
    Edge.objects.filter(team=team, target=target).delete()

    # parse query to extract dependencies and create edges
    try:
        model_name = saved_query.name
        dependencies = get_parents_from_model_query(team, model_name, model_query, database=database)
        for dependency_name in dependencies:
            source = resolve_dependency_to_node(dependency_name, team, database, dag)
            Edge.objects.create(
                team=team,
                dag=dag,
                source=source,
                target=target,
                properties=extra_properties,
            )
    except Exception:
        target.delete()
        raise

    # resolution succeeded, so an edge-less adoption marker no longer describes this node
    system = (target.properties or {}).get("system")
    if isinstance(system, dict):
        system.pop(DEGRADED_SYNC_KEY, None)
        if not system:
            target.properties.pop("system", None)

    # name is included in update_fields because Node.save() auto-syncs it from saved_query
    target.save(update_fields=["name", "type", "properties"])
    # After the save, so it reads fresh state under a row lock rather than riding along on the
    # whole-blob write above.
    clear_suspension_if_query_changed(target, saved_query.query)
    if reconcile:
        maybe_reconcile_dag(dag)
    return target


class HasDependentsError(Exception):
    """Raised when attempting to delete a saved query that has dependents."""

    pass


class MissingDagNodeError(Exception):
    """Raised when a saved query on a v2 team has no node to schedule through.

    On v2 the node is the unit of execution: the DAG run materializes nodes, so a saved query
    with no node is not reachable by any schedule. Without this the query would be left claiming
    to be materialized while nothing refreshes it.
    """

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
    nodes = Node.objects.filter(team=saved_query.team, saved_query=saved_query).select_related("dag", "dag__team")
    dags = {node.dag for node in nodes if node.dag is not None}
    nodes.delete()
    for dag in dags:
        maybe_reconcile_dag(dag)


def update_node_type(saved_query: "DataWarehouseSavedQuery", type: NodeType) -> None:
    """Update a Node's type to MAT_VIEW when materialized."""
    nodes = Node.objects.filter(team=saved_query.team, saved_query=saved_query).select_related("dag", "dag__team")
    dags = {node.dag for node in nodes if node.dag is not None}
    nodes.update(type=type)
    for dag in dags:
        maybe_reconcile_dag(dag)


def _promote_view_nodes(nodes: QuerySet[Node]) -> int:
    """Retype the nodes in `nodes` that a table backs but the graph still calls ephemeral views.

    `get_dag_structure` calls every VIEW node ephemeral, so a scheduled run reports success for one
    without materializing it and without writing a job row — it just stops updating, silently. A
    node ends up in that state because `revert_materialization` types it VIEW and, until the callers
    below existed, only the `materialize` action ever typed it back.

    Only VIEW nodes are touched: ENDPOINT nodes are a materializing type already and must keep
    theirs. Views with no backing table are left alone, being genuinely ephemeral. No reconcile
    follows, because tier membership keys off the node's frequency target, not its type.
    """
    return (
        nodes.filter(type=NodeType.VIEW, saved_query__table_id__isnull=False)
        .exclude(saved_query__deleted=True)
        .update(type=NodeType.MAT_VIEW)
    )


def promote_view_nodes_to_matview(saved_query: "DataWarehouseSavedQuery") -> int:
    """Repair one saved query's nodes, for the path that just linked its table."""
    return _promote_view_nodes(Node.objects.filter(team_id=saved_query.team_id, saved_query=saved_query))


def promote_dag_view_nodes_to_matview(dag: DAG) -> int:
    """Repair a whole DAG's nodes, for the tier conversion that is about to sweep its v1 schedules.

    v1 materializes a saved query whatever its node type, so a stranded node keeps running right up
    until that sweep and only goes dark afterwards.
    """
    return _promote_view_nodes(Node.objects.filter(dag=dag))
