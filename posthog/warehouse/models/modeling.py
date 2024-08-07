import collections.abc
import dataclasses
import typing
import uuid

from django.contrib.postgres import indexes as pg_indexes
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, models, transaction

from posthog.hogql import ast
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UpdatedMetaFields,
    UUIDModel,
    uuid7,
)
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.table import DataWarehouseTable

POSTHOG_ROOT_SOURCES = {
    "events",
    "groups",
    "persons",
    "person_distinct_ids",
    "session_replay_events",
    "cohort_people",
    "static_cohort_people",
    "log_entries",
    "sessions",
    "heatmaps",
}

LabelPath = list[str]


class LabelTreeField(models.Field):
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
    lookup_name = "lquery"

    def __init__(self, *args, **kwargs):
        self.prepare_rhs = False
        super().__init__(*args, **kwargs)

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return "%s ~ %s" % (lhs, rhs), params  # noqa: UP031


LabelTreeField.register_lookup(LabelQuery)


def get_hogql_query(query: str, team: Team) -> ast.SelectQuery | ast.SelectUnionQuery:
    from posthog.hogql.parser import parse_select

    parsed_query = parse_select(query)
    return parsed_query


def get_parents_from_model_query(model_query: str, team: Team):
    """Get parent models from a given query.

    This corresponds to any names in the FROM clause of the query.
    """
    hogql_query = get_hogql_query(query=model_query, team=team)

    if isinstance(hogql_query, ast.SelectUnionQuery):
        queries = hogql_query.select_queries
    else:
        queries = [hogql_query]

    parents = set()

    while queries:
        query = queries.pop()
        join = query.select_from

        if join is None:
            continue

        if isinstance(join.table, ast.SelectQuery):
            if join.table.view_name is not None:
                parents.add(join.table.view_name)
                continue

            queries.append(join.table)
        elif isinstance(join.table, ast.SelectUnionQuery):
            queries.extend(join.table.select_queries)

        while join is not None:
            parents.add(join.table.chain[0])  # type: ignore
            join = join.next_join
    return parents


NodeType = typing.Literal["SavedQuery", "Table", "PostHog"]
NodeId = str
Node = tuple[NodeId, NodeType]
Edge = tuple[NodeId, NodeId]


@dataclasses.dataclass
class DAG:
    """A basic DAG composed of nodes and edges."""

    edges: set[Edge]
    nodes: set[Node]


INSERT_QUERY = """\
insert into posthog_datawarehousemodelpath (
  id,
  team_id,
  table_id,
  saved_query_id,
  path,
  created_by_id,
  created_at,
  updated_at,
  deleted
) (
  select
    id,
    team_id,
    table_id,
    saved_query_id,
    parent.path || subpath(model_path.path, index(model_path.path, text2ltree(%(child)s))) as path,
    created_by_id,
    created_at,
    now() as updated_at,
    false as deleted
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


class DataWarehouseModelPathManager(models.Manager["DataWarehouseModelPath"]):
    def create_from_saved_query_instance(self, saved_query: DataWarehouseSavedQuery) -> "list[DataWarehouseModelPath]":
        """Create a new model path from a new `DataWarehouseSavedQuery`.

        Creating from a new `DataWarehouseSavedQuery` is straight-forward as we don't have to worry
        about this model having its own children paths that need updating: We are only adding a leaf
        node to all ancestor paths.

        Raises:
            ValueError: If no paths exists for the provided `DataWarehouseSavedQuery`.
        """
        if self.filter(team=saved_query.team, saved_query=saved_query).exists():
            raise ValueError("Model cannot be created as it already exists, use `update_from_saved_query_instance`")

        return self.create_from_saved_query(
            saved_query=saved_query.query["query"],
            team=saved_query.team,
            created_by=saved_query.created_by,
            saved_query_id=saved_query.id,
        )

    def create_from_saved_query(
        self, saved_query: str, team: Team, saved_query_id: uuid.UUID, created_by: User | None = None
    ) -> "list[DataWarehouseModelPath]":
        base_params = {
            "team": team,
            "created_by": created_by,
            "saved_query_id": saved_query_id,
            "table_id": None,
        }

        with transaction.atomic():
            parent_paths = []

            for parent in get_parents_from_model_query(saved_query, team):
                if parent in POSTHOG_ROOT_SOURCES:
                    parent_model_path, _ = self.get_or_create(
                        path=[parent],
                        team=team,
                        defaults={"deleted": False, "table": None, "saved_query": None},
                    )
                    parent_paths.append(parent_model_path.path)

                else:
                    try:
                        parent_query = DataWarehouseSavedQuery.objects.filter(team=team, name=parent).get()
                        parent_model_paths = self.filter(
                            team=team, saved_query=parent_query, path__lquery=f"*.{parent_query.id.hex}"
                        ).all()
                        parent_paths.extend(parent_model_path.path for parent_model_path in parent_model_paths)

                    except ObjectDoesNotExist:
                        parent_table = DataWarehouseTable.objects.filter(team=team, name=parent).get()

                        # Treat instances of `DataWarehouseTable` as root nodes
                        parent_model_path, _ = self.get_or_create(
                            path=[parent_table.id.hex],
                            team=team,
                            defaults={"table": parent_table, "deleted": False},
                        )
                        parent_paths.append(parent_model_path.path)

            results = self.bulk_create(
                [
                    DataWarehouseModelPath(id=uuid7(), path=[*parent_path, saved_query_id.hex], **base_params)
                    for parent_path in parent_paths
                ]
            )
        return results

    def update_from_saved_query_instance(self, saved_query: DataWarehouseSavedQuery) -> None:
        """Update model paths from an existing `DataWarehouseSavedQuery`."""
        if not self.filter(team=saved_query.team, saved_query=saved_query).exists():
            raise ValueError("Provided saved query contains no paths to update.")

        # Update descendants
        self.update_from_saved_query(
            saved_query=saved_query.query["query"],
            team=saved_query.team,
            saved_query_id=saved_query.id,
        )

    def update_from_saved_query(self, saved_query: str, team: Team, saved_query_id: uuid.UUID):
        parents = get_parents_from_model_query(saved_query, team)
        parent_ids = []

        with transaction.atomic():
            with connection.cursor() as cursor:
                for parent in parents:
                    if parent in POSTHOG_ROOT_SOURCES:
                        parent_id = parent
                    else:
                        try:
                            parent_query = DataWarehouseSavedQuery.objects.filter(team=team, name=parent).get()
                            parent_id = parent_query.id.hex
                        except ObjectDoesNotExist:
                            parent_table = DataWarehouseTable.objects.filter(team=team, name=parent).get()
                            parent_id = parent_table.id.hex

                    parent_ids.append(parent_id)

                    cursor.execute(
                        INSERT_QUERY, params={"child": saved_query_id.hex, "parent": parent_id, "team_id": team.pk}
                    )

                cursor.execute(DELETE_DUPLICATE_PATHS_QUERY, params={"team_id": team.pk})
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def get_paths_to_leaf_model(
        self, leaf_model: DataWarehouseSavedQuery | DataWarehouseTable
    ) -> "models.QuerySet[DataWarehouseModelPath]":
        """Return all paths to a leaf model."""
        return self.filter(path__lquery=f"*.{leaf_model.id.hex}").all()

    def get_longest_common_ancestor_path(
        self, leaf_models: collections.abc.Iterable[DataWarehouseSavedQuery | DataWarehouseTable]
    ) -> str | None:
        """Return the longest common ancestor path among paths from all leaf models, if any."""
        query = "select lca(array_agg(path)) from posthog_datawarehousemodelpath where path ? %(lqueries)s"

        with connection.cursor() as cursor:
            cursor.execute(query, params={"lqueries": [f"*.{leaf_model.id.hex}" for leaf_model in leaf_models]})
            row = cursor.fetchone()

        return row[0] or None

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
            if model_path.table is not None:
                node_type = "Table"
            elif model_path.saved_query is not None:
                node_type = "SavedQuery"
            else:
                node_type = "PostHog"

            for index, node_id in enumerate(model_path.path):
                try:
                    next_node_id = model_path.path[index + 1]
                except IndexError:
                    node: tuple[NodeId, NodeType] = (node_id, node_type)
                    nodes.add(node)
                else:
                    edges.add((node_id, next_node_id))

        return DAG(edges=edges, nodes=nodes)


class DataWarehouseModelPath(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    """Represent a path to a model."""

    class Meta:
        indexes = [
            models.Index(fields=("team_id", "path"), name="team_id_path"),
            models.Index(fields=("team_id", "table_id"), name="team_id_table_id"),
            models.Index(fields=("team_id", "saved_query_id"), name="team_id_saved_query_id"),
            pg_indexes.GistIndex("path", name="model_path_path"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("team_id", "path"), name="unique_team_id_path", deferrable=models.Deferrable.IMMEDIATE
            ),
        ]

    objects: DataWarehouseModelPathManager = DataWarehouseModelPathManager()

    path = LabelTreeField(null=False)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    table: models.ForeignKey = models.ForeignKey(DataWarehouseTable, null=True, default=None, on_delete=models.SET_NULL)
    saved_query: models.ForeignKey = models.ForeignKey(
        DataWarehouseSavedQuery, null=True, default=None, on_delete=models.SET_NULL
    )
