from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.settings import TEST


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
        super().__init__(clear_types=False)
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


class LazyTypeDetector(TraversingVisitor):
    """Detects any LazyJoinType or LazyTableType references in the AST.

    This is used to check if a query can be safely modified by predicate pushdown.
    If any field in the query references a lazy join, the pushdown would break
    because the inner subquery won't have those joins.

    Checks types on all typed nodes including Field, JoinExpr, Alias, and SelectQuery.
    """

    def __init__(self):
        super().__init__()
        self.found_lazy_type = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def visit_join_expr(self, node: ast.JoinExpr):
        super().visit_join_expr(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def visit_alias(self, node: ast.Alias):
        super().visit_alias(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def _check_type_for_lazy(self, field_type: ast.Type) -> bool:
        """Recursively check if a type contains lazy references."""
        if isinstance(field_type, ast.LazyJoinType):
            return True
        if isinstance(field_type, ast.LazyTableType):
            return True
        if isinstance(field_type, ast.FieldType):
            return self._check_table_type_for_lazy(field_type.table_type)
        if isinstance(field_type, ast.PropertyType):
            return self._check_type_for_lazy(field_type.field_type)
        if isinstance(field_type, ast.SelectQueryAliasType):
            # Check nested select query types for lazy references
            if field_type.select_query_type is not None:
                return self._check_select_query_type_for_lazy(field_type.select_query_type)
        return False

    def _check_table_type_for_lazy(self, table_type: ast.Type | None) -> bool:
        """Check if a table type references a lazy join."""
        if table_type is None:
            return False
        if isinstance(table_type, ast.LazyJoinType):
            return True
        if isinstance(table_type, ast.LazyTableType):
            return True
        if isinstance(table_type, ast.TableAliasType):
            return self._check_table_type_for_lazy(table_type.table_type)
        if isinstance(table_type, ast.SelectQueryAliasType):
            if table_type.select_query_type is not None:
                return self._check_select_query_type_for_lazy(table_type.select_query_type)
        return False

    def _check_select_query_type_for_lazy(self, query_type: ast.SelectQueryType | ast.SelectSetQueryType) -> bool:
        """Check if a select query type has lazy references in its tables."""
        if isinstance(query_type, ast.SelectSetQueryType):
            # For union queries, check each select in the union
            return False
        for table_type in query_type.tables.values():
            if self._check_table_type_for_lazy(table_type):
                return True
        for table_type in query_type.anonymous_tables:
            if self._check_table_type_for_lazy(table_type):
                return True
        return False


class EventsFieldCollector(TraversingVisitor):
    """Collects database columns that reference direct database columns on a specific table.

    Collects both the database column names AND the resolved FieldTypes so that the
    inner subquery can be built with proper types without calling resolve_types again.

    Also tracks whether any field references non-direct fields (like FieldTraversers)
    or lazy joins which would prevent safe predicate pushdown.
    """

    def __init__(self, target_table: ast.TableType | ast.TableAliasType, context: HogQLContext):
        super().__init__()
        self.target_table = target_table
        self.context = context
        # Map of database column name -> FieldType (with resolved types from the AST)
        self.collected_fields: dict[str, ast.FieldType] = {}
        self.has_non_direct_fields = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        field_type = node.type

        # PropertyType represents property access like events.properties.$session_id
        # After resolution, these may be converted to materialized column references
        # which won't work after we wrap events in a subquery. Skip pushdown for safety.
        if isinstance(field_type, ast.PropertyType):
            # Check if this property access is on our target table
            if isinstance(field_type.field_type, ast.FieldType):
                if self._matches_target_table(field_type.field_type.table_type):
                    self.has_non_direct_fields = True
                    return
            field_type = field_type.field_type

        if isinstance(field_type, ast.FieldType):
            table_type = field_type.table_type

            # If this field references a lazy join, we can't safely apply pushdown
            # because the inner subquery won't have that join
            # This catches cases like events.poe.distinct_id where the field has LazyJoinType
            if self._type_references_lazy_join(table_type):
                self.has_non_direct_fields = True
                return

            # Check if this field references our target table
            if self._matches_target_table(table_type):
                db_column_name = self._get_database_column_name(field_type)
                if db_column_name:
                    # Collect both the column name and its resolved FieldType
                    self.collected_fields[db_column_name] = field_type
                else:
                    # Found a non-direct field (FieldTraverser, etc.)
                    # This means predicate pushdown may break join conditions
                    self.has_non_direct_fields = True

    def _type_references_lazy_join(self, table_type: ast.Type | None) -> bool:
        """Check if a type references a lazy join anywhere in its chain."""
        if table_type is None:
            return False
        if isinstance(table_type, ast.LazyJoinType):
            return True
        if isinstance(table_type, ast.TableAliasType):
            return self._type_references_lazy_join(table_type.table_type)
        if isinstance(table_type, ast.LazyTableType):
            return True
        if isinstance(table_type, ast.VirtualTableType):
            return self._type_references_lazy_join(table_type.table_type)
        return False

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
        unwrapped: ast.Type = table_type
        if isinstance(unwrapped, ast.TableAliasType):
            unwrapped = unwrapped.table_type
        if isinstance(unwrapped, ast.VirtualTableType):
            unwrapped = unwrapped.table_type
        if isinstance(unwrapped, ast.TableAliasType):
            unwrapped = unwrapped.table_type

        target: ast.Type = self.target_table
        if isinstance(target, ast.TableAliasType):
            target = target.table_type

        # Check if it's the same table (by comparing the actual Table object)
        if isinstance(unwrapped, ast.TableType) and isinstance(target, ast.TableType):
            return unwrapped.table is target.table

        # Identity check as fallback
        return table_type is self.target_table or unwrapped is target


class TypeRewriter(CloningVisitor):
    """Rewrites field types in an expression to reference a new table type.

    Used when building the inner subquery to update WHERE clause field types
    to reference the inner events table instead of the outer query's table.
    """

    def __init__(self, table_type: ast.TableType, columns_in_scope: dict[str, ast.Type]):
        super().__init__(clear_types=False)
        self.table_type = table_type
        self.columns_in_scope = columns_in_scope

    def visit_field(self, node: ast.Field):
        # Get the field name - for simple fields it's the first element,
        # for table-qualified fields like ['events', 'timestamp'] it's the last element
        if len(node.chain) == 1:
            field_name = str(node.chain[0])
        elif len(node.chain) == 2:
            # Table-qualified: ['events', 'timestamp'] -> 'timestamp'
            field_name = str(node.chain[1])
        else:
            # For longer chains, clone without modification
            return ast.Field(chain=node.chain.copy(), type=node.type)

        if field_name in self.columns_in_scope:
            # Create a new field with updated type, using just the field name
            return ast.Field(
                chain=[field_name],
                type=ast.FieldType(name=field_name, table_type=self.table_type),
            )

        # For other fields, clone with their original type
        return ast.Field(chain=node.chain.copy(), type=node.type)


class EventsPredicatePushdownTransform(TraversingVisitor):
    """
    Transform that pushes WHERE predicates into events subqueries.

    Runs AFTER resolve_lazy_tables. At this point:
    - Lazy joins have been resolved into actual JoinExpr nodes
    - Joined table aliases are visible via next_join chain

    The transform replaces the events table reference with a subquery
    containing the pushed-down predicates:
    FROM events -> FROM (SELECT <needed_columns> FROM events WHERE <predicates>) AS events

    Applies at every nesting level (bottom-up) so user-written subqueries
    that SELECT FROM events with joins also benefit from pushdown.
    """

    # Pushdown is safe when events (always the left/FROM side) is on the preserved side.
    # RIGHT JOIN and FULL OUTER JOIN preserve the right side, so filtering events
    # before the join would incorrectly turn matched rows into NULL-padded rows.
    _SAFE_JOIN_TYPES = {"JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "CROSS JOIN"}

    def __init__(self, context: HogQLContext, dialect: HogQLDialect = "clickhouse"):
        super().__init__()
        self.context = context
        self.dialect = dialect
        self._nesting_depth = 0  # Track query nesting

    def visit_select_query(self, node: ast.SelectQuery):
        # Track nesting depth for debugging/testing
        self._nesting_depth += 1
        try:
            # First visit children (subqueries) - pushdown applied bottom-up
            super().visit_select_query(node)

            # Check if this query is eligible for predicate pushdown
            # This includes checking for lazy types that would break pushdown
            if self._should_apply_pushdown(node):
                # Apply the pushdown transformation
                self._apply_pushdown(node)
        finally:
            self._nesting_depth -= 1

    def _apply_pushdown(self, node: ast.SelectQuery) -> None:
        """Apply predicate pushdown to an eligible query."""
        assert node.select_from is not None

        # Collect joined table aliases from the JOIN chain
        joined_aliases = self._collect_joined_aliases(node)
        if not joined_aliases:
            return

        # Get the events table type from the outer query (needed for both
        # predicate extraction and subquery building)
        events_table_type = node.select_from.type
        # We only apply pushdown to events table which should be TableType or TableAliasType
        if not isinstance(events_table_type, (ast.TableType, ast.TableAliasType)):
            return

        # Extract pushable predicates from WHERE and PREWHERE separately
        # so each clause retains its semantics (PREWHERE stays PREWHERE)
        extractor = EventsPredicatePushdownExtractor(
            joined_table_aliases=joined_aliases,
            events_table_type=events_table_type,
        )

        inner_from_where: ast.Expr | None = None
        inner_from_prewhere: ast.Expr | None = None

        if node.where is not None:
            inner_from_where, node.where = extractor.get_pushdown_predicates(node.where)
        if node.prewhere is not None:
            inner_from_prewhere, node.prewhere = extractor.get_pushdown_predicates(node.prewhere)

        # Combine inner (pushable) predicates from both clauses
        inner_parts = [p for p in [inner_from_where, inner_from_prewhere] if p is not None]
        if not inner_parts:
            return
        inner_where = inner_parts[0] if len(inner_parts) == 1 else ast.And(exprs=inner_parts)

        # Collect all columns the outer query needs from the events table
        needed_columns = self._collect_needed_columns(node, events_table_type)

        # If no columns are needed, skip pushdown (can happen with aliased tables in edge cases)
        if not needed_columns:
            return

        # Get the table alias if present (e.g., 'e' from 'FROM events AS e')
        table_alias = node.select_from.alias

        # Remove table alias prefix from field chains
        # This converts chains like ['e', 'timestamp'] to ['timestamp'] so they can
        # be resolved correctly in the inner subquery context
        inner_where = TableAliasPrefixRemover(alias_to_remove=table_alias).visit(inner_where)
        inner_where = clone_expr(inner_where)

        # Build the subquery with proper types manually (without calling resolve_types)
        # This avoids the issue where resolve_types tries to resolve HogQL abstract columns
        # which may include lazy joins, when we only want raw database columns
        # Note: team_id filter is added inside _build_typed_subquery
        events_subquery = self._build_typed_subquery(needed_columns, inner_where)

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
        # TODO: Update field references in the outer query so metadata accurately reflects the transformed
        assert events_subquery.type is not None  # We always set the type in _build_typed_subquery
        node.select_from.type = ast.SelectQueryAliasType(
            alias=new_alias,
            select_query_type=events_subquery.type,
        )

    def _should_apply_pushdown(self, node: ast.SelectQuery) -> bool:
        """Check if this query is eligible for predicate pushdown.

        Applies to any query where:
        - FROM events (directly, not a subquery)
        - Has WHERE or PREWHERE clause
        - Has joins (lazy or explicit)
        """
        return (
            (self.context.modifiers.pushDownPredicates or (self.context.modifiers.pushDownPredicates is None and TEST))
            and node.select_from is not None
            and node.select_from.sample is None  # No SAMPLE clause
            and isinstance(node.select_from.table, ast.Field)
            and node.select_from.table.chain == ["events"]
            and (node.where is not None or node.prewhere is not None)
            and node.select_from.next_join is not None  # Has joins
        )

    def _collect_joined_aliases(self, node: ast.SelectQuery) -> set[str]:
        """Collect aliases from the JOIN chain.

        Returns an empty set if any join uses an unsafe type (e.g. RIGHT JOIN,
        FULL OUTER JOIN), which causes _apply_pushdown to bail out.
        """
        aliases: set[str] = set()
        join = node.select_from.next_join if node.select_from else None
        while join is not None:
            if join.join_type and join.join_type not in self._SAFE_JOIN_TYPES:
                return set()
            if join.alias:
                aliases.add(join.alias)
            join = join.next_join
        return aliases

    def _collect_needed_columns(
        self, node: ast.SelectQuery, events_table_type: ast.TableType | ast.TableAliasType
    ) -> dict[str, ast.FieldType] | None:
        """
        Walk the outer query and collect database columns that reference the events table.

        Returns a dict mapping database column names to their resolved FieldTypes,
        or None if the query cannot safely be transformed.

        This includes fields from:
        - SELECT clause
        - WHERE clause (both pushable and non-pushable predicates)
        - GROUP BY, ORDER BY, HAVING
        - JOIN constraints (e.g., $session_id for session join ON clause)
        """
        # First check if the query has any lazy type references that weren't fully resolved
        # These would cause errors after we modify the FROM clause
        lazy_detector = LazyTypeDetector()
        lazy_detector.visit(node)
        if lazy_detector.found_lazy_type:
            return None

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        # If the query uses non-direct fields, we can't safely apply pushdown
        # because join conditions may reference fields that won't exist in the subquery
        if collector.has_non_direct_fields:
            return None

        return collector.collected_fields

    def _build_typed_subquery(
        self, collected_fields: dict[str, ast.FieldType], where_clause: ast.Expr
    ) -> ast.SelectQuery:
        """Build a subquery using the already-resolved types from the outer query.

        Uses the collected FieldTypes to build the subquery, avoiding the need to
        call resolve_types which might resolve HogQL abstract columns to lazy joins.
        """
        # Get the inner table type by unwrapping any alias from the collected fields
        # All fields should reference the same underlying table
        inner_table_type: ast.TableType | None = None
        for field_type in collected_fields.values():
            table_type = field_type.table_type
            # Unwrap TableAliasType and VirtualTableType to get the underlying TableType
            while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
                table_type = table_type.table_type
            if isinstance(table_type, ast.TableType):
                inner_table_type = table_type
                break

        if inner_table_type is None:
            # Fallback: this shouldn't happen for valid events queries
            raise ValueError("Could not determine inner table type from collected fields")

        # Build typed Field nodes for each column, wrapped in Alias to ensure
        # the column names are preserved even if PropertySwapper transforms the inner expression
        select_fields: list[ast.Expr] = []
        columns_in_scope: dict[str, ast.Type] = {}

        for col_name in sorted(collected_fields.keys()):
            original_field_type = collected_fields[col_name]

            if isinstance(original_field_type.table_type, ast.VirtualTableType):
                # Recreate the VirtualTableType wrapping the inner table
                virtual_table_type = ast.VirtualTableType(
                    table_type=inner_table_type,
                    field=original_field_type.table_type.field,
                    virtual_table=original_field_type.table_type.virtual_table,
                )
                # Use the original HogQL field name (e.g., "properties"), not the db column name
                field_type = ast.FieldType(name=original_field_type.name, table_type=virtual_table_type)
            else:
                field_type = ast.FieldType(name=col_name, table_type=inner_table_type)

            field_node = ast.Field(chain=[col_name], type=field_type)
            alias_node = ast.Alias(alias=col_name, expr=field_node, type=field_type)
            select_fields.append(alias_node)

            # Track for the SelectQueryType
            columns_in_scope[col_name] = field_type

        # Create the JoinExpr for FROM events
        events_field = ast.Field(chain=["events"], type=inner_table_type)
        select_from = ast.JoinExpr(table=events_field, type=inner_table_type)

        # Build the SelectQueryType
        select_query_type = ast.SelectQueryType(
            columns=columns_in_scope,
            tables={"events": inner_table_type},
        )

        # Type the WHERE clause fields to reference the inner table
        where_clause = TypeRewriter(inner_table_type, columns_in_scope).visit(where_clause)

        # Create the subquery
        return ast.SelectQuery(
            select=select_fields,
            select_from=select_from,
            where=where_clause,
            type=select_query_type,
        )
