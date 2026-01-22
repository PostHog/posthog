from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import (
    EventsPredicatePushdownExtractor,
    unwrap_table_aliases,
)
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def apply_events_predicate_pushdown(
    node: _T_AST,
    context: HogQLContext,
) -> _T_AST:
    """Apply predicate pushdown to events tables with lazy joins.

    The transform modifies the AST in place but also returns it for chaining.
    """
    EventsPredicatePushdownTransform(context=context, dialect="clickhouse").visit(node)
    return node


class EventsFieldCollector(TraversingVisitor):
    """Collects all field names that reference a specific table type."""

    def __init__(self, target_table: ast.TableType | ast.TableAliasType):
        super().__init__()
        self.target_table = target_table
        self.fields: set[str] = set()

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if isinstance(node.type, ast.FieldType):
            # Check if this field references our target table
            table_type = node.type.table_type
            if self._matches_target_table(table_type):
                self.fields.add(node.type.name)

    def _matches_target_table(self, table_type: ast.Type | None) -> bool:
        """Check if a table type matches our target table."""
        if table_type is None:
            return False

        # Unwrap TableAliasType to get underlying TableType
        if isinstance(table_type, ast.TableAliasType):
            table_type = table_type.table_type

        target = self.target_table
        if isinstance(target, ast.TableAliasType):
            target = target.table_type

        # Check if it's the same table
        if isinstance(table_type, ast.TableType) and isinstance(target, ast.TableType):
            return table_type.table is target.table

        return table_type is target


class EventsPredicatePushdownTransform(TraversingVisitor):
    """
    Transform that pushes WHERE predicates into events subqueries.

    Runs AFTER resolve_lazy_tables. At this point:
    - Lazy joins have been resolved into actual JoinExpr nodes
    - Joined table aliases are visible via next_join chain

    The transform replaces the events table reference with a subquery
    containing the pushed-down predicates:
    FROM events -> FROM (SELECT <needed_columns> FROM events WHERE <predicates>) AS events
    """

    def __init__(self, context: HogQLContext, dialect: HogQLDialect = "clickhouse"):
        super().__init__()
        self.context = context
        self.dialect = dialect

    def visit_select_query(self, node: ast.SelectQuery):
        # First visit children (subqueries)
        super().visit_select_query(node)

        # Check if this query is eligible for predicate pushdown
        if not self._should_apply_pushdown(node):
            return

        assert node.select_from is not None
        assert node.where is not None

        # Collect joined table aliases from the JOIN chain
        joined_aliases = self._collect_joined_aliases(node)
        if not joined_aliases:
            return

        # Extract pushable predicates
        extractor = EventsPredicatePushdownExtractor(joined_table_aliases=joined_aliases)
        inner_where, _outer_where = extractor.get_pushdown_predicates(node.where)

        if inner_where is None:
            return

        # Get the events table type from the outer query
        events_table_type = node.select_from.type
        if events_table_type is None:
            return

        # Collect all columns the outer query needs from the events table
        needed_columns = self._collect_needed_columns(node, events_table_type)

        # Unwrap table aliases for the inner subquery WHERE
        inner_where = unwrap_table_aliases(inner_where)

        # Clear types since inner_where will be re-resolved in the inner subquery context
        inner_where = clone_expr(inner_where, clear_types=True)

        # Add team_id filter for security and performance
        subquery_where = self._add_team_id_filter(inner_where)

        # Build SELECT list with only the needed columns (not SELECT *)
        select_fields = self._build_select_fields(needed_columns)

        # Create inner subquery with explicit columns
        events_subquery = ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=subquery_where,
        )

        # Resolve types for the subquery - now safe because we're selecting
        # specific columns, not SELECT * which expands to include lazy columns
        events_subquery = cast(
            ast.SelectQuery,
            resolve_types(events_subquery, self.context, self.dialect, []),
        )

        # Replace the events table with the subquery
        # Preserve the original alias (e.g., "e" from "FROM events AS e")
        # If no alias was specified, use "events" as the alias
        original_alias = node.select_from.alias
        new_alias = original_alias or "events"
        node.select_from.table = events_subquery
        node.select_from.alias = new_alias

        # Set the JoinExpr type to SelectQueryAliasType so the printer knows to print
        # the subquery. Field references in the outer query still point to their original
        # types which is fine - they don't need to know about the subquery wrapper.
        node.select_from.type = ast.SelectQueryAliasType(
            alias=new_alias,
            select_query_type=events_subquery.type,
        )

    def _should_apply_pushdown(self, node: ast.SelectQuery) -> bool:
        """Check if this query is eligible for predicate pushdown."""
        return (
            node.select_from is not None
            and node.select_from.sample is None  # No SAMPLE clause
            and isinstance(node.select_from.table, ast.Field)
            and node.select_from.table.chain == ["events"]
            and node.where is not None
            and node.select_from.next_join is not None  # Has joins
        )

    def _collect_joined_aliases(self, node: ast.SelectQuery) -> set[str]:
        """Collect aliases from the JOIN chain."""
        aliases: set[str] = set()
        join = node.select_from.next_join if node.select_from else None
        while join is not None:
            if join.alias:
                aliases.add(join.alias)
            join = join.next_join
        return aliases

    def _collect_needed_columns(
        self, node: ast.SelectQuery, events_table_type: ast.TableType | ast.TableAliasType
    ) -> set[str]:
        """
        Walk the outer query and collect all field names that reference the events table.

        This includes fields from:
        - SELECT clause
        - WHERE clause (both pushable and non-pushable predicates)
        - GROUP BY, ORDER BY, HAVING
        - JOIN constraints (e.g., $session_id for session join ON clause)
        """
        collector = EventsFieldCollector(events_table_type)
        collector.visit(node)
        return collector.fields

    def _build_select_fields(self, columns: set[str]) -> list[ast.Expr]:
        """Build untyped Field nodes for the needed columns."""
        # Sort for deterministic output
        return [ast.Field(chain=[col_name]) for col_name in sorted(columns)]

    def _add_team_id_filter(self, inner_where: ast.Expr) -> ast.Expr:
        """Add team_id filter to the pushdown predicate."""
        if self.context.team_id is None:
            return inner_where

        # Create team_id filter without types - resolve_types will handle typing
        team_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["team_id"]),
            right=ast.Constant(value=self.context.team_id),
        )
        return ast.And(exprs=[team_id_filter, inner_where])
