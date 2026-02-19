import enum
import uuid
import dataclasses

from django.contrib.postgres import indexes as pg_indexes
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, models, transaction

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import Resolver
from posthog.hogql.resolver_utils import extract_select_queries

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable

LabelPath = list[str]


class CycleDetectingResolver(Resolver):
    """A resolver that detects circular dependencies in view references.

    This extends the base Resolver to track which views are currently being
    resolved, raising a QueryError if a cycle is detected.
    """

    def __init__(self, *args, initial_view_name: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        # seeded with the current view name so its "visited"
        self.resolving_views: set[str] = {initial_view_name} if initial_view_name else set()

    def visit_join_expr(self, node: ast.JoinExpr):
        """Override to add cycle detection when resolving views."""
        # CTEs are handled entirely by the parent class, but for views we track visited for cycle detection
        if isinstance(node.table, ast.Field) and self.database is not None:
            try:
                database_table = self.database.get_table([str(n) for n in node.table.chain])
            except QueryError:
                pass  # falls through to the parent class
            else:
                if isinstance(database_table, SavedQuery):
                    view_name = database_table.name
                    if view_name in self.resolving_views:
                        raise QueryError(f"Circular dependency detected in view '{view_name}'")
                    self.resolving_views.add(view_name)
                    try:
                        return super().visit_join_expr(node)
                    finally:
                        self.resolving_views.discard(view_name)

        return super().visit_join_expr(node)


class LabelTreeField(models.Field):
    """A Django model field for a PostgreSQL label tree.

    We represent label trees in Python as a list of strings, each item
    in the list being one of the labels of the underlying ltree.
    """

    description = "A PostgreSQL label tree field provided by the ltree extension"

    def db_type(self, connection):
        return "ltree"

    def from_db_value(self, value, expression, connection) -> None | LabelPath:
        if value is None:
            return value

        return value.split(".")

    def to_python(self, value) -> None | LabelPath:
        if value is None:
            return value

        if isinstance(value, list):
            return value

        return value.split(".")

    def get_prep_value(self, value: LabelPath) -> str:
        return ".".join(value)


class LabelQuery(models.Lookup):
    """Implement a lookup for an ltree label query using the ~ operator."""

    lookup_name = "lquery"

    def __init__(self, *args, **kwargs):
        self.prepare_rhs = False
        super().__init__(*args, **kwargs)

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return "%s ~ %s" % (lhs, rhs), params  # noqa: UP031


class LabelQueryArray(models.Lookup):
    """Implement a lookup for an array of ltree label queries using the ? operator."""

    lookup_name = "lqueryarray"

    def __init__(self, *args, **kwargs):
        self.prepare_rhs = False
        super().__init__(*args, **kwargs)

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return "%s ? %s" % (lhs, rhs), params  # noqa: UP031


LabelTreeField.register_lookup(LabelQuery)
LabelTreeField.register_lookup(LabelQueryArray)


def get_parents_from_model_query(team: Team, model_name: str, model_query: str) -> set[str]:
    """Get parents from a given query.

    The parents of a query are any names in the `FROM` clause of the query.
    Uses CycleDetectingResolver to detect circular dependencies in view references.

    Args:
        model_query: The HogQL query string to parse
        team: The team context for database resolution
        view_name: Optional name of the view being parsed. If provided, cycles back to
                   this view through other views will be detected.
    """
    from posthog.hogql.context import HogQLContext

    hogql_query = parse_select(model_query)
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        enable_select_queries=True,
    )
    if context.database is None:
        context.database = Database.create_for(
            context.team_id,
            modifiers=context.modifiers,
            team=context.team,
        )

    # use cycledetectingresolver to resolve types and detect circular view dependencies
    resolver = CycleDetectingResolver(context=context, dialect="hogql", initial_view_name=model_name)
    prepared_ast = resolver.visit(hogql_query)

    if prepared_ast is None:
        return set()

    if isinstance(prepared_ast, ast.SelectSetQuery):
        queries = list(extract_select_queries(prepared_ast))
    else:
        queries = [prepared_ast]

    # collect CTE definitions so we can resolve through them to find real tables
    ctes: dict[str, ast.CTE] = {}
    for q in queries:
        if q.ctes:
            ctes.update(q.ctes)

    parents: set[str] = set()

    while queries:
        query = queries.pop()

        join = query.select_from

        if join is None:
            continue

        while join is not None:
            if isinstance(join.table, ast.SelectQuery):
                if join.table.view_name is not None:
                    parents.add(join.table.view_name)
                    break

                queries.append(join.table)
                break
            elif isinstance(join.table, ast.SelectSetQuery):
                queries.extend(list(extract_select_queries(join.table)))
                break

            if isinstance(join.table, ast.Placeholder):
                parent_name = join.table.field
            elif isinstance(join.table, ast.Field):
                parent_name = ".".join(str(s) for s in join.table.chain)
            else:
                raise ValueError(f"No handler for {join.table.__class__.__name__} in get_parents_from_model_query")

            if isinstance(parent_name, str):
                if parent_name in ctes:
                    cte_expr = ctes[parent_name].expr
                    if isinstance(cte_expr, ast.SelectSetQuery):
                        queries.extend(list(extract_select_queries(cte_expr)))
                    elif isinstance(cte_expr, ast.SelectQuery):
                        queries.append(cte_expr)
                else:
                    parents.add(parent_name)

            join = join.next_join

    return parents


class NodeType(enum.Enum):
    SAVED_QUERY = "SavedQuery"
    POSTHOG = "PostHog"
    TABLE = "Table"


NodeId = str
Node = tuple[NodeId, NodeType]
Edge = tuple[NodeId, NodeId]


@dataclasses.dataclass
class DAG:
    """A basic DAG composed of nodes and edges."""

    edges: set[Edge]
    nodes: set[Node]


UPDATE_PATHS_QUERY = """\
insert into posthog_datawarehousemodelpath (
  id,
  team_id,
  table_id,
  saved_query_id,
  path,
  created_by_id,
  created_at,
  updated_at
) (
  select distinct on (id)
    id,
    team_id,
    table_id,
    saved_query_id,
    parent.path || subpath(model_path.path, index(model_path.path, text2ltree(%(child)s))) as path,
    created_by_id,
    created_at,
    now() as updated_at
  from
    posthog_datawarehousemodelpath as model_path,
    (
      select
        path
      from posthog_datawarehousemodelpath
      where path ~ ('*.' || %(parent)s)::lquery
      and team_id = %(team_id)s
    ) as parent
  where
    model_path.path ~ ('*.' || %(child)s || '.*')::lquery
    and team_id = %(team_id)s
  order by id, path
)
on conflict (id) do
update
  set path = EXCLUDED.path,
      updated_at = now()
"""

DELETE_DUPLICATE_PATHS_QUERY = """\
delete from posthog_datawarehousemodelpath
where
  team_id = %(team_id)s
  and id in (
    select id
    from (
      select id, row_number() over (partition by team_id, path) as row_number
      from posthog_datawarehousemodelpath
    ) partitioned
    where partitioned.row_number > 1
);
"""

CYCLE_CHECK_QUERY = """\
select exists (
  select 1
  from posthog_datawarehousemodelpath
  where team_id = %(team_id)s
  and path ~ ('*.' || %(child)s || '.*.' || %(parent)s)::lquery
)
"""


class ModelPathCycleError(Exception):
    """Exception raised when a cycle would be created in the model DAG."""

    def __init__(self, child: str, parent: str):
        super().__init__(f"Adding {parent} as a parent of {child} would create a cycle in the DAG")
        self.child = child
        self.parent = parent


class UnknownParentError(Exception):
    """Exception raised when the parent for a model is not found."""

    def __init__(self, parent: str, query: str):
        super().__init__(
            f"The parent name {parent} does not correspond to an existing PostHog table, Data Warehouse Table, or Data Warehouse Saved Query."
        )
        self.query = query


class ModelPathAlreadyExistsError(Exception):
    """Exception raised when trying to create paths for a model that already has some."""

    def __init__(self, model_name: str):
        super().__init__(f"Model {model_name} cannot be created as it already exists")


class ModelPathDoesNotExistError(Exception):
    """Exception raised when trying to update paths for a model that doesn't exist."""

    def __init__(self, model_name: str):
        super().__init__(f"Model {model_name} doesn't exist")


class DataWarehouseModelPathManager(models.Manager["DataWarehouseModelPath"]):
    """A model manager that implements some common path operations."""

    def create_from_saved_query(self, saved_query: DataWarehouseSavedQuery) -> "list[DataWarehouseModelPath]":
        """Create one or more model paths from a new `DataWarehouseSavedQuery`.

        Creating one or more model paths from a new `DataWarehouseSavedQuery` is straight-forward as we
        don't have to worry about this model having its own children paths that need updating: We are
        only adding a leaf node to all parents' paths. We check this model indeed does not exist to
        ensure that is the case.

        Raises:
            ValueError: If no paths exists for the provided `DataWarehouseSavedQuery`.
        """
        return self.create_leaf_paths_from_query(
            team=saved_query.team,
            model_name=saved_query.name,
            model_query=saved_query.query["query"],
            saved_query_id=saved_query.id,
            created_by=saved_query.created_by,
            label=saved_query.id.hex,
        )

    def create_leaf_paths_from_query(
        self,
        team: Team,
        model_name: str,
        model_query: str,
        label: str,
        saved_query_id: uuid.UUID,
        created_by: User | None = None,
        table_id: uuid.UUID | None = None,
    ) -> "list[DataWarehouseModelPath]":
        """Create all paths to a new leaf model.

        A path will be created for each parent, as extracted from the given query.
        """
        with transaction.atomic():
            if self.filter(team=team, saved_query_id=saved_query_id).exists():
                raise ModelPathAlreadyExistsError(saved_query_id.hex)

            parent_paths = self.get_or_create_query_parent_paths(team, model_name, model_query)

            # If we don't have any parent paths then we can treat ourselves as a root node
            # This can happen when creating a query that returns a static set of rows, like a SELECT 1.e
            paths = [[*model_path.path, label] for model_path in parent_paths]
            if not paths:
                paths = [[label]]

            results: list[DataWarehouseModelPath] = []
            for path in paths:
                model, _ = DataWarehouseModelPath.objects.get_or_create(
                    team=team,
                    saved_query_id=saved_query_id,
                    table_id=table_id,
                    path=path,
                    defaults={"created_by": created_by},
                )
                results.append(model)

        return results

    def get_or_create_root_path_for_posthog_source(
        self, posthog_source_name: str, team: Team
    ) -> tuple["DataWarehouseModelPath", bool]:
        """Get a root path for a PostHog source, creating it if it doesn't exist.

        PostHog sources are well-known PostHog tables. We check against the team's HogQL database
        to ensure that the source exists before creating the path.

        Raises:
            ValueError: If the provided `posthog_source_name` is not a PostHog table.

        Returns:
            A tuple with the model path and a `bool` indicating whether it was created or not.
        """
        try:
            self.get_hogql_database(team).get_table(posthog_source_name)
        except QueryError:
            raise ValueError(f"Provided source {posthog_source_name} is not a PostHog table")

        return self.get_or_create(path=[posthog_source_name], team=team, defaults={"saved_query": None})

    def get_hogql_database(self, team: Team) -> Database:
        """Get the HogQL database for given team."""
        return Database.create_for(team=team)

    def get_or_create_root_path_for_data_warehouse_table(
        self, data_warehouse_table: DataWarehouseTable
    ) -> tuple["DataWarehouseModelPath", bool]:
        """Get a root path for a `DataWarehouseTable`, creating it if it doesn't exist.

        A `DataWarehouseTable` is loaded by us into S3 or read directly from an external data source,
        like our user's S3 bucket or their PostgreSQL database.

        Either way, it is a table we can consider a root node, as it's managed by data warehouse
        data import workflows.

        Returns:
            A tuple with the model path and a `bool` indicating whether it was created or not.
        """
        table_id = data_warehouse_table.id
        return self.get_or_create(
            path=[table_id.hex],
            team=data_warehouse_table.team,
            defaults={"saved_query": None, "table": data_warehouse_table},
        )

    def filter_all_leaf_paths(self, leaf_id: str | uuid.UUID, team: Team):
        """Filter all paths to leaf node given by `leaf_id`."""
        if isinstance(leaf_id, uuid.UUID):
            leaf_id = leaf_id.hex
        return self.filter(team=team, path__lquery=f"*.{leaf_id}")

    def get_or_create_query_parent_paths(
        self, team: Team, model_name: str, model_query: str
    ) -> list["DataWarehouseModelPath"]:
        """Get a list of model paths for a query's parents, creating root nodes if they do not exist."""
        parent_paths = []
        for parent in get_parents_from_model_query(team, model_name, model_query):
            try:
                parent_query = (
                    DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(team=team, name=parent).get()
                )
            except ObjectDoesNotExist:
                pass
            else:
                parent_query_paths = list(self.filter_all_leaf_paths(parent_query.id.hex, team=team).all())
                parent_paths.extend(parent_query_paths)
                continue

            try:
                table = self.get_hogql_database(team).get_table(parent)
                if not isinstance(table, HogQLDataWarehouseTable):
                    raise ObjectDoesNotExist()

                if table.table_id:
                    parent_table = (
                        DataWarehouseTable.objects.exclude(deleted=True).filter(team=team, id=table.table_id).get()
                    )
                else:
                    parent_table = (
                        DataWarehouseTable.objects.exclude(deleted=True).filter(team=team, name=table.name).get()
                    )

            except (ObjectDoesNotExist, QueryError):
                pass
            else:
                parent_path, _ = self.get_or_create_root_path_for_data_warehouse_table(parent_table)
                parent_paths.append(parent_path)
                continue

            try:
                parent_path, _ = self.get_or_create_root_path_for_posthog_source(parent, team)
            except ValueError:
                pass
            else:
                parent_paths.append(parent_path)
                continue

            raise UnknownParentError(parent, model_query)

        return parent_paths

    def update_from_saved_query(self, saved_query: DataWarehouseSavedQuery) -> None:
        """Update model paths from an existing `DataWarehouseSavedQuery`."""
        if not self.filter(team=saved_query.team, saved_query=saved_query).exists():
            raise ValueError("Provided saved query contains no paths to update.")

        self.update_paths_from_query(
            team=saved_query.team,
            model_name=saved_query.name,
            model_query=saved_query.query["query"],
            label=saved_query.id.hex,
            saved_query_id=saved_query.id,
        )

    def update_paths_from_query(
        self,
        team: Team,
        model_name: str,
        model_query: str,
        label: str,
        saved_query_id: uuid.UUID | None = None,
        table_id: uuid.UUID | None = None,
    ) -> None:
        """Update all model paths from a given query.

        We parse the query to extract all its direct parents. Then, we update all the paths
        that contain `label` to add an edge from parent and `label`, effectively removing the
        previous parent path.

        This may lead to duplicate paths, so we have to defer constraints, until the end of
        the transaction and clean them up.
        """
        parents = get_parents_from_model_query(team, model_name, model_query)
        posthog_table_names = self.get_hogql_database(team).get_posthog_table_names()

        base_params = {
            "team_id": team.pk,
            "saved_query_id": saved_query_id,
            "table_id": table_id,
        }

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")

                for parent in parents:
                    if parent in posthog_table_names:
                        parent_id = parent
                    else:
                        try:
                            parent_query = (
                                DataWarehouseSavedQuery.objects.exclude(deleted=True)
                                .filter(team=team, name=parent)
                                .get()
                            )
                        except ObjectDoesNotExist:
                            try:
                                table = self.get_hogql_database(team).get_table(parent)
                                if not isinstance(table, HogQLDataWarehouseTable):
                                    raise ObjectDoesNotExist()

                                if table.table_id:
                                    parent_table = (
                                        DataWarehouseTable.objects.exclude(deleted=True)
                                        .filter(team=team, id=table.table_id)
                                        .get()
                                    )
                                else:
                                    parent_table = (
                                        DataWarehouseTable.objects.exclude(deleted=True)
                                        .filter(team=team, name=table.name)
                                        .get()
                                    )
                            except (ObjectDoesNotExist, QueryError):
                                raise UnknownParentError(parent, model_query)
                            else:
                                parent_id = parent_table.id.hex
                        else:
                            parent_id = parent_query.id.hex

                    cursor.execute(CYCLE_CHECK_QUERY, params={"team_id": team.pk, "child": label, "parent": parent_id})
                    if cursor.fetchone()[0]:
                        raise ModelPathCycleError(child=label, parent=parent_id)

                    cursor.execute(UPDATE_PATHS_QUERY, params={**{"child": label, "parent": parent_id}, **base_params})

                cursor.execute(DELETE_DUPLICATE_PATHS_QUERY, params={"team_id": team.pk})
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def get_dag(self, team: Team):
        """Return a DAG of all the models for the given team.

        A DAG is composed by a set of edges and a set of nodes, where each node is a tuple
        of a node id and type, and each edge is a pair of two nodes. The edges are directed in the
        order of the tuple elements.

        TODO:
        * Should we resolve node id and node type to their underlying models?
        * Edges could be indexed by node if required by callers.
        * Certain paths can be redundant and could be excluded from the query.
        """
        edges = set()
        nodes: set[Node] = set()
        node_type: NodeType
        node_id: NodeId

        for model_path in self.filter(team=team).select_related("saved_query", "table").all():
            if model_path.saved_query is not None:
                node_type = NodeType.SAVED_QUERY
            elif model_path.table is not None:
                node_type = NodeType.TABLE
            else:
                node_type = NodeType.POSTHOG

            for index, node_id in enumerate(model_path.path):
                try:
                    next_node_id = model_path.path[index + 1]
                except IndexError:
                    node: tuple[NodeId, NodeType] = (node_id, node_type)
                    nodes.add(node)
                else:
                    edges.add((node_id, next_node_id))

        return DAG(edges=edges, nodes=nodes)


class DataWarehouseModelPath(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Django model to represent paths to a data warehouse model.

    A data warehouse model is represented by a saved query, and the path to it contains all
    tables and views that said query is selecting from, recursively all the way to root
    PostHog tables and external data source tables.
    """

    class Meta:
        indexes = [
            models.Index(fields=("team_id", "path"), name="team_id_path"),
            models.Index(fields=("team_id", "saved_query_id"), name="team_id_saved_query_id"),
            pg_indexes.GistIndex("path", name="model_path_path"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("team_id", "path"), name="unique_team_id_path", deferrable=models.Deferrable.IMMEDIATE
            ),
        ]
        db_table = "posthog_datawarehousemodelpath"

    objects: DataWarehouseModelPathManager = DataWarehouseModelPathManager()

    path = LabelTreeField(null=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    table = models.ForeignKey(DataWarehouseTable, null=True, default=None, on_delete=models.SET_NULL)
    saved_query = models.ForeignKey(DataWarehouseSavedQuery, null=True, default=None, on_delete=models.SET_NULL)
