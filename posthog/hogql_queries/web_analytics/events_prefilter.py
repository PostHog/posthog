from typing import Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.visitor import TraversingVisitor

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator


class _EventsFieldCollector(TraversingVisitor):
    """Collects all events-table field names referenced anywhere in the query."""

    def __init__(self, events_table_type: ast.Type):
        super().__init__()
        self.events_table_type = events_table_type
        self.fields: set[str] = set()

    def visit_field(self, node: ast.Field):
        field_type = node.type
        # PropertyType (e.g. events.properties.$pathname) wraps the underlying FieldType
        if isinstance(field_type, ast.PropertyType):
            field_type = field_type.field_type
        if isinstance(field_type, ast.FieldType) and field_type.table_type == self.events_table_type:
            self.fields.add(field_type.name)


class EventsPrefilterTransformer(TraversingVisitor):
    """Wraps FROM events in a resolved AST with a prefiltered subquery.

    Used by WebStatsTableQueryRunner to push timestamp predicates into
    the events table scan before the expensive session and person override
    JOINs that the lazy resolver attaches.

    After transformation, each FROM events becomes:
        FROM (SELECT <columns> FROM events WHERE <prefilter>) AS events

    Must run on a fully-resolved AST (after lazy table resolution)
    and is intentionally scoped to WebStatsTableQueryRunner.
    """

    def __init__(self, team_id: int, date_from: str, date_to: str):
        super().__init__()
        self.team_id = team_id
        self.date_from = date_from
        self.date_to = date_to
        self.wraps_applied = 0

    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)

        if node.select_from is None:
            return
        join = node.select_from
        if not isinstance(join.table, ast.Field) or join.table.chain != ["events"]:
            return

        events_table_type = join.type

        def make_field(name: str) -> ast.Field:
            return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=events_table_type))

        prefilter = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=make_field("team_id"),
                    right=ast.Constant(value=self.team_id),
                    op=ast.CompareOperationOp.Eq,
                ),
                ast.CompareOperation(
                    left=ast.Call(name="toDate", args=[make_field("timestamp")]),
                    right=ast.Constant(value=self.date_from),
                    op=ast.CompareOperationOp.GtEq,
                ),
                ast.CompareOperation(
                    left=ast.Call(name="toDate", args=[make_field("timestamp")]),
                    right=ast.Constant(value=self.date_to),
                    op=ast.CompareOperationOp.LtEq,
                ),
            ]
        )

        # Collect ALL events-table fields from the entire query (SELECT, WHERE, GROUP BY, JOINs)
        collector = _EventsFieldCollector(events_table_type)
        collector.visit(node)
        events_columns = collector.fields
        # Always include columns needed by JOIN constraints and the prefilter itself
        events_columns.update(["team_id", "timestamp", "distinct_id", "$session_id_uuid"])

        inner_join = ast.JoinExpr(table=join.table, type=events_table_type)
        subquery = ast.SelectQuery(
            # Bare fields (no ast.Alias) so ClickHouse column names pass through
            # directly — the printer resolves each to its CH name, matching what
            # the outer query expects.
            select=[make_field(c) for c in sorted(events_columns)],
            select_from=inner_join,
            where=prefilter,
            type=ast.SelectQueryType(),
        )

        join.table = subquery
        join.alias = "events"
        join.type = ast.SelectQueryAliasType(alias="events", select_query_type=subquery.type)
        self.wraps_applied += 1


class PrefilterHogQLHasMorePaginator(HogQLHasMorePaginator):
    """Paginator that applies the events prefilter AST transformation before execution."""

    def __init__(self, *, team_id: int, date_from: str, date_to: str, **kwargs):
        super().__init__(**kwargs)
        self.team_id = team_id
        self.date_from = date_from
        self.date_to = date_to

    @classmethod
    def from_limit_context(
        cls,
        *,
        limit_context: LimitContext,
        team_id: int,
        date_from: str,
        date_to: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> "PrefilterHogQLHasMorePaginator":
        from posthog.hogql.constants import get_default_limit_for_context, get_max_limit_for_context

        max_rows = get_max_limit_for_context(limit_context)
        default_rows = get_default_limit_for_context(limit_context)
        limit = min(max_rows, default_rows if (limit is None or limit <= 0) else limit)
        return cls(
            limit=limit,
            offset=offset,
            limit_context=limit_context,
            team_id=team_id,
            date_from=date_from,
            date_to=date_to,
        )

    def execute_hogql_query(
        self,
        query: Union[ast.SelectQuery, ast.SelectSetQuery],
        *,
        query_type: str,
        **kwargs,
    ) -> "HogQLQueryResponse":  # noqa: F821
        from posthog.schema import HogQLQueryResponse

        from posthog.hogql.printer.utils import print_prepared_ast
        from posthog.hogql.query import HogQLQueryExecutor

        executor = HogQLQueryExecutor(
            query=self.paginate(query),
            query_type=query_type,
            **kwargs if self.limit_context is None else {"limit_context": self.limit_context, **kwargs},
        )
        executor._prepare_execution()

        if executor.clickhouse_prepared_ast is not None:
            transformer = EventsPrefilterTransformer(
                team_id=self.team_id,
                date_from=self.date_from,
                date_to=self.date_to,
            )
            transformer.visit(executor.clickhouse_prepared_ast)

            assert executor.clickhouse_context is not None
            executor.clickhouse_sql = print_prepared_ast(
                node=executor.clickhouse_prepared_ast,
                context=executor.clickhouse_context,
                dialect="clickhouse",
                pretty=True,
            )

        executor._execute_clickhouse_query()
        self.response = HogQLQueryResponse(
            query=None,
            hogql=executor.hogql,
            clickhouse=executor.clickhouse_sql,
            results=executor.results,
            columns=executor.print_columns,
            types=executor.types,
            timings=executor.timings.to_list(),
            modifiers=executor.query_modifiers,
        )
        self.results = self.trim_results()
        return self.response
