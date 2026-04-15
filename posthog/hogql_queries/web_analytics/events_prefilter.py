from __future__ import annotations

from typing import TYPE_CHECKING, Union

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.visitor import TraversingVisitor

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryResponse

    from posthog.hogql.database.models import Table


class _EventsFieldCollector(TraversingVisitor):
    """Collects events-table field names and property accesses from the entire query."""

    def __init__(self, events_table_type: ast.Type):
        super().__init__()
        self.events_table_type = events_table_type
        self.fields: set[str] = set()
        self.property_accesses: set[tuple[str, str]] = set()  # (property_name, table_column)

    def visit_field(self, node: ast.Field):
        field_type = node.type
        if isinstance(field_type, ast.PropertyType):
            ft = field_type.field_type
            if ft.table_type == self.events_table_type and len(field_type.chain) >= 1:
                self.property_accesses.add((str(field_type.chain[0]), ft.name))
            field_type = ft
        if isinstance(field_type, ast.FieldType) and field_type.table_type == self.events_table_type:
            self.fields.add(field_type.name)


class EventsPrefilterTransformer(TraversingVisitor):
    """Wraps FROM events in a resolved AST with a prefiltered subquery.

    Used by WebStatsTableQueryRunner to push timestamp predicates into
    the events table scan before the expensive session and person override
    JOINs that the lazy resolver attaches.

    After transformation, each FROM events becomes:
        FROM (SELECT <columns> FROM events WHERE <prefilter>) AS events

    Materialized columns (mat_$pathname, etc.) are resolved at print time
    by the HogQL printer and bypass the AST type system. This transformer
    detects which mat columns the query needs and adds them to the subquery
    SELECT, temporarily registering them on the events table schema so the
    printer can resolve them. If any property access lacks a mat column,
    the `properties` JSON column is included as fallback for JSONExtractRaw.

    Must run on a fully-resolved AST (after lazy table resolution)
    and is intentionally scoped to WebStatsTableQueryRunner.
    """

    def __init__(self, team_id: int, date_from: str, date_to: str):
        super().__init__()
        self.team_id = team_id
        self.date_from = date_from
        self.date_to = date_to
        self.wraps_applied = 0
        self._temp_schema_fields: list[tuple[object, str]] = []

    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)

        if node.select_from is None:
            return
        join = node.select_from
        if not isinstance(join.table, ast.Field) or join.table.chain != ["events"]:
            return

        events_table_type = join.type
        if events_table_type is None:
            return

        def make_field(name: str) -> ast.Field:
            return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=events_table_type))

        prefilter = ast.And(
            exprs=[
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
        events_columns.update(["timestamp", "distinct_id", "$session_id_uuid"])

        # Resolve materialized columns for property accesses
        mat_column_names = self._resolve_materialized_columns(
            collector.property_accesses, events_columns, events_table_type
        )

        inner_join = ast.JoinExpr(table=join.table, type=events_table_type)
        subquery = ast.SelectQuery(
            # Bare fields (no ast.Alias) so ClickHouse column names pass through
            # directly — the printer resolves each to its CH name, matching what
            # the outer query expects.
            select=[make_field(c) for c in sorted(events_columns | mat_column_names)],
            select_from=inner_join,
            where=prefilter,
            type=ast.SelectQueryType(),
        )

        join.table = subquery
        join.alias = "events"
        assert subquery.type is not None
        join.type = ast.SelectQueryAliasType(alias="events", select_query_type=subquery.type)
        self.wraps_applied += 1

    def _resolve_materialized_columns(
        self,
        property_accesses: set[tuple[str, str]],
        events_columns: set[str],
        events_table_type: ast.Type,
    ) -> set[str]:
        """Resolve property accesses to materialized column names.

        For each property access (e.g. $pathname on properties), checks if a
        materialized column exists (mat_$pathname). If so, temporarily registers
        it on the events table schema and returns the name. If any property
        lacks a mat column, keeps `properties` in events_columns for JSONExtractRaw.
        """
        from typing import cast

        from posthog.hogql.database.models import StringDatabaseField

        from posthog.clickhouse.materialized_columns import get_enabled_materialized_columns
        from posthog.models.property import TableColumn

        if not property_accesses:
            events_columns.discard("properties")
            return set()

        mat_cols_map = get_enabled_materialized_columns("events")
        mat_column_names: set[str] = set()
        has_unmaterialized = False

        for prop_name, table_col in property_accesses:
            key = (prop_name, cast(TableColumn, table_col))
            if key in mat_cols_map:
                ch_name = mat_cols_map[key].name
                mat_column_names.add(ch_name)
                # Temporarily register on the events table so the printer can resolve it
                table = self._get_events_table(events_table_type)
                if table is not None and ch_name not in table.fields:
                    table.fields[ch_name] = StringDatabaseField(name=ch_name)
                    self._temp_schema_fields.append((table, ch_name))
            else:
                has_unmaterialized = True

        # Only keep properties if some accesses can't use mat columns
        if not has_unmaterialized:
            events_columns.discard("properties")

        return mat_column_names

    @staticmethod
    def _get_events_table(table_type: ast.Type) -> Table | None:
        from posthog.hogql.database.models import Table as TableModel

        if isinstance(table_type, ast.TableType):
            return table_type.table if isinstance(table_type.table, TableModel) else None
        if isinstance(table_type, ast.TableAliasType):
            return EventsPrefilterTransformer._get_events_table(table_type.table_type)
        return None

    def cleanup_temp_schema_fields(self):
        for table, field_name in self._temp_schema_fields:
            if hasattr(table, "fields") and field_name in table.fields:
                del table.fields[field_name]
        self._temp_schema_fields.clear()


class PrefilterHogQLHasMorePaginator(HogQLHasMorePaginator):
    """Paginator that applies the events prefilter AST transformation before execution."""

    def __init__(self, *, team_id: int, date_from: str, date_to: str, **kwargs):
        super().__init__(**kwargs)
        self.team_id = team_id
        self.date_from = date_from
        self.date_to = date_to

    @classmethod
    def create(
        cls,
        *,
        limit_context: LimitContext,
        team_id: int,
        date_from: str,
        date_to: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PrefilterHogQLHasMorePaginator:
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
    ) -> HogQLQueryResponse:
        from posthog.schema import HogQLQueryResponse

        from posthog.hogql.constants import get_default_hogql_global_settings
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
            try:
                transformer.visit(executor.clickhouse_prepared_ast)

                assert executor.clickhouse_context is not None
                settings = get_default_hogql_global_settings(executor.team.pk, executor.settings)
                executor.clickhouse_sql = print_prepared_ast(
                    node=executor.clickhouse_prepared_ast,
                    context=executor.clickhouse_context,
                    dialect="clickhouse",
                    settings=settings,
                    pretty=True,
                )
            finally:
                transformer.cleanup_temp_schema_fields()

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
