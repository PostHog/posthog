from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q, QuerySet

import structlog

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery as HogQLSavedQuery
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError

from products.data_modeling.backend.facade.contracts import Dependent
from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
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


def materializes(saved_query: "DataWarehouseSavedQuery") -> bool:
    """Whether a saved query is asking to be materialized.

    `is_materialized` is the customer's intent, and `table` is one artifact of acting on it. The two
    come apart, because `table` is `on_delete=SET_NULL`: a backing table that goes away nulls
    `table_id` and leaves the intent untouched. Reading the artifact instead of the intent then
    types the node VIEW, which `get_dag_structure` calls ephemeral and a run skips, so the table can
    never come back and the query stops updating for good, without an error.

    Managed views are excluded because their flag is not a statement of intent: the Revenue
    Analytics viewsets set `is_materialized` at provisioning, before anything runs, so reading it
    would enroll a large population of views that have never materialized a row.
    """
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    if saved_query.origin == DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET:
        return saved_query.table_id is not None
    # The column is nullable, and NULL predates its default: it means the same as False here, which
    # is also how `_materializes_q` reads it.
    return bool(saved_query.is_materialized)


def node_type_for(saved_query: "DataWarehouseSavedQuery") -> NodeType:
    """The node type a saved query's DAG node should carry."""
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    if saved_query.origin == DataWarehouseSavedQuery.Origin.ENDPOINT:
        return NodeType.ENDPOINT
    if materializes(saved_query):
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
        # `database` can outlive the row it was built from, and a caller reusing one schema across a
        # batch widens that window. A view renamed or deleted since then is an unresolvable name,
        # which `on_unresolved` gets to rule on, not a failure that costs every other dependency.
        saved_query = DataWarehouseSavedQuery.objects.filter(team=team, name=dependency_name, deleted=False).first()
        if saved_query is None:
            raise UnknownParentError(dependency_name, "")
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


def _lock_dag(team_id: int, dag_id: UUID) -> None:
    """Serialize against every other writer of this DAG's edges.

    The same key `Edge._detect_cycles` takes, so an edge write and a node delete cannot interleave.
    Callers holding more than one DAG take them in a fixed order, so two of them cannot deadlock.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team_id, str(dag_id)])


def replace_incoming_edges(
    target: Node,
    dependency_names: Iterable[str],
    *,
    team: "Team",
    dag: DAG,
    database: Database,
    on_unresolved: Literal["raise", "skip"],
    extra_properties: dict | None = None,
) -> list[str]:
    """Rebuild every incoming edge of `target` from `dependency_names`, and report what did not resolve.

    The whole replacement runs in one transaction behind the advisory lock `Edge.save` already takes,
    so two concurrent syncs of the same node run one after the other instead of leaving the union of
    both edge sets, and a failure part-way through leaves the previous edges in place rather than an
    edge-less node.

    With `on_unresolved="skip"` a name that matches no node is collected and returned; with "raise"
    it propagates.
    """
    unresolved: list[str] = []
    with transaction.atomic():
        _lock_dag(team.pk, dag.id)
        Node.objects.select_for_update().filter(pk=target.pk).first()
        Edge.objects.filter(team=team, target=target).delete()
        for dependency_name in dependency_names:
            try:
                source = resolve_dependency_to_node(dependency_name, team, database, dag)
            except (UnknownParentError, Node.DoesNotExist):
                if on_unresolved == "raise":
                    raise
                logger.warning(
                    "Skipped an unresolvable lineage dependency",
                    dependency_name=dependency_name,
                    node_id=str(target.pk),
                    team_id=team.pk,
                )
                unresolved.append(dependency_name)
                continue
            Edge.objects.create(
                team=team,
                dag=dag,
                source=source,
                target=target,
                properties=extra_properties or {},
            )
    return unresolved


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

    # Internal DAG sync (no user); bypass warehouse HogQL access control so dependency resolution
    # sees every referenced table/view.
    if database is None:
        database = Database.create_for(
            team=team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )
    # parsed before the node exists, so a query that cannot be parsed leaves nothing to undo
    model_name = saved_query.name
    dependencies = get_parents_from_model_query(team, model_name, model_query, database=database)

    # The node is created in the same transaction that rebuilds its edges, so a failure part-way
    # through leaves no node rather than an edge-less one. A concurrent sync of the same query
    # cannot adopt the node until this transaction commits, so it can no longer lose the edges it
    # wrote to a node this call then deletes.
    with transaction.atomic():
        target, _ = Node.objects.get_or_create(
            team=team,
            saved_query=saved_query,
            dag=dag,
            defaults={"name": saved_query.name, "type": node_type, "properties": extra_properties},
        )
        # update type (name is automatically synced from saved_query in Node.save())
        target.type = node_type
        replace_incoming_edges(
            target,
            dependencies,
            team=team,
            dag=dag,
            database=database,
            on_unresolved="raise",
            extra_properties=extra_properties,
        )

        # resolution succeeded, so an edge-less adoption marker no longer describes this node
        target.clear_lineage_markers()

        # name is included in update_fields because Node.save() auto-syncs it from saved_query
        target.save(update_fields=["name", "type", "properties"])
    # After the save, so it reads fresh state under a row lock rather than riding along on the
    # whole-blob write above.
    clear_suspension_if_query_changed(target, saved_query.query)
    if reconcile:
        maybe_reconcile_dag(dag)
    return target


def _nameless_refusal(view_name: str) -> str:
    return f"Can't delete {view_name} yet. Something else reads from it. Update or delete it first."


class HasDependentsError(Exception):
    """Raised when attempting to delete a saved query that has dependents.

    Names no dependent. Only a caller that has filtered `dependents` through the reader's access
    may name one, so a caller that logs or renders `str(err)` cannot disclose one by accident.
    """

    def __init__(
        self,
        view_name: str,
        dependents: tuple[Dependent, ...] = (),
        fallback_node_id: str | None = None,
    ) -> None:
        super().__init__(_nameless_refusal(view_name))
        self.view_name = view_name
        self.dependents = dependents
        self.fallback_node_id = fallback_node_id


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
    from this saved query's nodes (i.e., they reference this view in their query).

    Every node of the saved query counts, not just one: the delete removes all of them, so a
    dependent hanging off a second DAG's node would lose its edge without ever blocking the delete.
    A dependent that reads the query in more than one DAG is reported once, at its oldest node, so
    the returned order is deterministic even when the query has nodes in several DAGs.
    """
    nodes = Node.objects.filter(team=saved_query.team, saved_query=saved_query)
    dependent_nodes = (
        Node.objects.filter(
            team=saved_query.team,
            incoming_edges__source__in=nodes,
            saved_query__isnull=False,
        )
        .select_related("saved_query")
        .order_by("created_at", "id")
    )
    dependents: dict[str, DataWarehouseSavedQuery] = {}
    for dependent_node in dependent_nodes:
        dependent = dependent_node.saved_query
        if dependent is not None and not dependent.deleted:
            dependents.setdefault(str(dependent.id), dependent)
    return list(dependents.values())


DEPENDENT_KIND_LABELS: dict[str, str] = {
    NodeType.VIEW: "view",
    NodeType.MAT_VIEW: "materialized view",
    NodeType.ENDPOINT: "endpoint",
    NodeType.METRIC: "metric",
}

MAX_NAMED_DEPENDENTS = 3


def _dependent_metrics(nodes: QuerySet[Node]) -> list[Dependent]:
    """Metrics reading any of `nodes`, each pointing at the node it hangs off.

    Every node of the saved query counts, not just one: the delete removes all of them, so a metric
    hanging off a second DAG's node would lose its edge without ever blocking the delete. The node
    travels with the name so the refusal can point at a graph the metric is in.
    """
    source_by_metric: dict[str, str] = {}
    rows = Node.objects.filter(
        team_id__in=nodes.values("team_id"), incoming_edges__source__in=nodes, type=NodeType.METRIC
    ).values_list("name", "incoming_edges__source_id")
    for name, source_id in rows:
        source_by_metric.setdefault(name, str(source_id))
    return [
        Dependent(name=name, kind=NodeType.METRIC, lineage_node_id=source_node_id)
        for name, source_node_id in sorted(source_by_metric.items())
    ]


def describe_dependents(view_name: str, dependents: Sequence[Dependent], *, any_hidden: bool = False) -> str:
    """The message a person reads when a delete is refused, naming at most three dependents.

    `dependents` must already be filtered to what the reader may see, and the count in the overflow
    tail is taken over that list, so the tail cannot report how many were withheld.
    """
    if not dependents:
        if any_hidden:
            return (
                f"Can't delete {view_name} yet. Something you don't have access to reads from it. "
                "Ask a project admin to find what depends on it."
            )
        return _nameless_refusal(view_name)

    named = dependents[:MAX_NAMED_DEPENDENTS]
    listed = ", ".join(f"{dependent.name} ({DEPENDENT_KIND_LABELS.get(dependent.kind, 'view')})" for dependent in named)
    remaining = len(dependents) - len(named)
    if remaining:
        listed = f"{listed}, and {remaining} more"
    if any_hidden:
        return (
            f"Can't delete {view_name} yet. These read from it: {listed}. Something you don't have access to "
            "reads from it too. Update or delete the ones listed, then ask a project admin about the rest."
        )
    return f"Can't delete {view_name} yet. These read from it: {listed}. Update or delete them first."


def blocked_lineage_node_id(dependents: Sequence[Dependent], fallback_node_id: str | None) -> str | None:
    """The node the refusal's "view lineage" link should open.

    A metric only appears in the DAG its edge lives in, so the link has to open the node that metric
    hangs off. `fallback_node_id` covers a delete that only saved queries blocked, where every DAG
    shows a blocker. Pass only the dependents the reader may see: a link into a metric's DAG is
    itself a signal that a metric exists.
    """
    for dependent in dependents:
        if dependent.lineage_node_id is not None:
            return dependent.lineage_node_id
    return fallback_node_id


def _oldest_node_id(nodes: QuerySet[Node]) -> str | None:
    oldest_node = nodes.order_by("created_at").first()
    return str(oldest_node.id) if oldest_node else None


def delete_node_from_dag(saved_query: "DataWarehouseSavedQuery") -> None:
    """
    Delete the Node for a SavedQuery (cascades to edges)

    Must be called BEFORE soft_delete() due to on_delete=PROTECT on the saved_query FK.
    """
    nodes = Node.objects.filter(team=saved_query.team, saved_query=saved_query).select_related("dag", "dag__team")
    with transaction.atomic():
        # Hold every DAG this query has a node in, so a sync cannot attach a dependent between the
        # check below and the delete that would cascade its edge away.
        dags = sorted({node.dag for node in nodes if node.dag is not None}, key=lambda dag: str(dag.id))
        for dag in dags:
            _lock_dag(saved_query.team_id, dag.id)

        query_dependents = [
            Dependent(
                name=dependent.name,
                kind=node_type_for(dependent),
                saved_query_id=str(dependent.id),
                created_by_id=dependent.created_by_id,
            )
            for dependent in get_dependent_saved_queries(saved_query)
        ]
        dependents = query_dependents + _dependent_metrics(nodes)
        if dependents:
            raise HasDependentsError(
                saved_query.name,
                tuple(dependents),
                fallback_node_id=_oldest_node_id(nodes),
            )
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


def _materializes_q() -> Q:
    """`materializes` as a filter, for the callers that cannot ask row by row."""
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    managed = Q(saved_query__origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET)
    return (~managed & Q(saved_query__is_materialized=True)) | (managed & Q(saved_query__table_id__isnull=False))


def _promote_view_nodes(nodes: QuerySet[Node]) -> int:
    """Retype the nodes in `nodes` that materialize but the graph still calls ephemeral views.

    `get_dag_structure` calls every VIEW node ephemeral, so a scheduled run reports success for one
    without materializing it and without writing a job row — it just stops updating, silently. A
    node ends up in that state because `revert_materialization` types it VIEW and, until the callers
    below existed, only the `materialize` action ever typed it back.

    Only VIEW nodes are touched: ENDPOINT nodes are a materializing type already and must keep
    theirs. Views nobody asked to materialize are left alone, being genuinely ephemeral. No
    reconcile follows, because tier membership keys off the node's frequency target, not its type.
    """
    return (
        nodes.filter(_materializes_q(), type=NodeType.VIEW)
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
