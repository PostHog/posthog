from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr


def apply_events_predicate_pushdown(
    node: _T_AST,
    context: HogQLContext,
) -> _T_AST:
    """Apply predicate pushdown to events tables with lazy joins.

    The transform modifies the AST in place but also returns it for chaining.
    """
    EventsPredicatePushdownTransform(context=context, dialect="clickhouse").visit(node)
    return node


class TableAliasPrefixRemover(CloningVisitor):
    """
    Clones an expression and removes table alias prefixes from field chains.

    When pushing predicates into a subquery, fields like ['e', 'timestamp'] need to become
    ['timestamp'] because the inner subquery doesn't have the alias 'e' - it's just 'events'.
    """

    def __init__(self, alias_to_remove: str | None):
        super().__init__()
        self.alias_to_remove = alias_to_remove

    def visit_field(self, node: ast.Field):
        new_chain = node.chain.copy()

        # Remove alias prefix from chain if present
        # e.g., ['e', 'timestamp'] -> ['timestamp'] when alias is 'e'
        if self.alias_to_remove and len(new_chain) > 1 and new_chain[0] == self.alias_to_remove:
            new_chain = new_chain[1:]

        return ast.Field(
            chain=new_chain,
            type=node.type,
        )


class EventsFieldCollector(TraversingVisitor):
    """Collects database column names that reference direct database columns on a specific table.

    Collects the actual database column names (not HogQL field names) so that the
    inner subquery can select them without aliases. This ensures that column names
    in the subquery match what the outer query expects.

    Also tracks whether any field references non-direct fields (like FieldTraversers)
    which would prevent safe predicate pushdown.
    """

    def __init__(self, target_table: ast.TableType | ast.TableAliasType, context: HogQLContext):
        super().__init__()
        self.target_table = target_table
        self.context = context
        # Collect database column names, not HogQL field names
        self.database_columns: set[str] = set()
        self.has_non_direct_fields = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        field_type = node.type

        # Handle PropertyType which wraps a FieldType
        if isinstance(field_type, ast.PropertyType):
            field_type = field_type.field_type

        if isinstance(field_type, ast.FieldType):
            # Check if this field references our target table
            table_type = field_type.table_type
            if self._matches_target_table(table_type):
                db_column_name = self._get_database_column_name(field_type)
                if db_column_name:
                    self.database_columns.add(db_column_name)
                else:
                    # Found a non-direct field (FieldTraverser, etc.)
                    # This means predicate pushdown may break join conditions
                    self.has_non_direct_fields = True

    def _get_database_column_name(self, field_type: ast.FieldType) -> str | None:
        """Get the database column name for a field, or None if not a direct database field."""
        from posthog.hogql.database.models import DatabaseField, FieldTraverser

        try:
            resolved = field_type.resolve_database_field(self.context)
            # FieldTraversers are not direct database fields
            if isinstance(resolved, FieldTraverser):
                return None
            if isinstance(resolved, DatabaseField):
                return resolved.name
            return None
        except Exception:
            return None

    def _matches_target_table(self, table_type: ast.Type | None) -> bool:
        """Check if a table type matches our target table."""
        if table_type is None:
            return False

        # Get the underlying TableType from both sides
        unwrapped = table_type
        if isinstance(unwrapped, ast.TableAliasType):
            unwrapped = unwrapped.table_type

        target = self.target_table
        if isinstance(target, ast.TableAliasType):
            target = target.table_type

        # Check if it's the same table (by comparing the actual Table object)
        if isinstance(unwrapped, ast.TableType) and isinstance(target, ast.TableType):
            return unwrapped.table is target.table

        # Identity check as fallback
        return table_type is self.target_table or unwrapped is target


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

        # If no columns are needed, skip pushdown (can happen with aliased tables in edge cases)
        if not needed_columns:
            return

        # Get the table alias if present (e.g., 'e' from 'FROM events AS e')
        table_alias = node.select_from.alias

        # Remove table alias prefix from field chains and clear types
        # This converts chains like ['e', 'timestamp'] to ['timestamp'] so they can
        # be resolved correctly in the inner subquery context
        inner_where = TableAliasPrefixRemover(alias_to_remove=table_alias).visit(inner_where)
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
        # specific database columns, not SELECT * which expands to include lazy columns
        events_subquery = cast(
            ast.SelectQuery,
            resolve_types(events_subquery, self.context, self.dialect, []),
        )

        # Also resolve lazy tables in case any of the columns trigger lazy joins
        resolve_lazy_tables(events_subquery, self.dialect, [], self.context)

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
    ) -> set[str] | None:
        """
        Walk the outer query and collect database column names that reference the events table.

        Collects actual database column names (not HogQL field names) so that the
        inner subquery can select them without aliases.

        Returns None if the query uses non-direct fields (like FieldTraversers) which
        would break join conditions after predicate pushdown.

        This includes fields from:
        - SELECT clause
        - WHERE clause (both pushable and non-pushable predicates)
        - GROUP BY, ORDER BY, HAVING
        - JOIN constraints (e.g., $session_id for session join ON clause)
        """
        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        # If the query uses non-direct fields, we can't safely apply pushdown
        # because join conditions may reference fields that won't exist in the subquery
        if collector.has_non_direct_fields:
            return None

        return collector.database_columns

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
