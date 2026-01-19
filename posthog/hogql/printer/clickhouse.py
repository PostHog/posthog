from datetime import date, datetime
from typing import Literal, Union, cast
from uuid import UUID

from posthog.schema import PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.ast import AST
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DANGEROUS_NoTeamIdCheckTable, DatabaseField, SavedQuery
from posthog.hogql.database.s3_table import DataWarehouseTable, S3Table
from posthog.hogql.errors import ImpossibleASTError, InternalHogQLError, QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string, safe_identifier
from posthog.hogql.printer.base import HogQLPrinter, resolve_field_type
from posthog.hogql.printer.types import PrintableMaterializedColumn, PrintableMaterializedPropertyGroupItem
from posthog.hogql.utils import ilike_matches, like_matches
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.property_groups import property_groups
from posthog.models.utils import UUIDT


def team_id_guard_for_table(table_type: ast.TableOrSelectType, context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.team_id:
        raise InternalHogQLError("context.team_id not found")

    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["team_id"], type=ast.FieldType(name="team_id", table_type=table_type)),
        right=ast.Constant(value=context.team_id),
        type=ast.BooleanType(),
    )


# In non-nullable materialized columns, these values are treated as NULL
MAT_COL_NULL_SENTINELS = ["", "null"]

# We skip nullIf/ifNull wrapping for these columns, to improve performance and help skip index usage
COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING = {
    "mat_$ai_trace_id",
    "mat_$ai_session_id",
    "mat_$ai_is_error",
    "$ai_trace_id",
    "$ai_session_id",
    "$ai_is_error",
}


class ClickHousePrinter(HogQLPrinter):
    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["clickhouse"],
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty)

    def visit(self, node: AST | None):
        if node is None:
            return ""
        response = super().visit(node)

        if len(self.stack) == 0 and self.settings:
            if not isinstance(node, ast.SelectQuery) and not isinstance(node, ast.SelectSetQuery):
                raise QueryError("Settings can only be applied to SELECT queries")
            settings = self._print_settings(self.settings)
            if settings is not None:
                response += " " + settings

        return response

    def visit_select_query(self, node: ast.SelectQuery):
        if not self.context.enable_select_queries:
            raise InternalHogQLError("Full SELECT queries are disabled if context.enable_select_queries is False")
        if not self.context.team_id:
            raise InternalHogQLError("Full SELECT queries are disabled if context.team_id is not set")

        return super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr):
        if node.type is None:
            raise InternalHogQLError("Printing queries with a FROM clause is not permitted before type resolution")
        return super().visit_join_expr(node)

    def visit_and(self, node: ast.And):
        """
        optimizations:
        1. and(expr0, 1, expr2, ...) <=> and(expr0, expr2, ...)
        2. and(expr0, 0, expr2, ...) <=> 0
        """
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        exprs: list[str] = []
        for expr in node.exprs:
            printed = self.visit(expr)
            if printed == "0":  # optimization 2
                return "0"
            if printed != "1":  # optimization 1
                exprs.append(printed)
        if len(exprs) == 0:
            return "1"
        elif len(exprs) == 1:
            return exprs[0]
        return f"and({', '.join(exprs)})"

    def visit_or(self, node: ast.Or):
        """
        optimizations:
        1. or(expr0, 1, expr2, ...) <=> 1
        2. or(expr0, 0, expr2, ...) <=> or(expr0, expr2, ...)
        """
        if len(node.exprs) == 1:
            return self.visit(node.exprs[0])

        exprs: list[str] = []
        for expr in node.exprs:
            printed = self.visit(expr)
            if printed == "1":
                return "1"
            if printed != "0":
                exprs.append(printed)
        if len(exprs) == 0:
            return "0"
        elif len(exprs) == 1:
            return exprs[0]
        return f"or({', '.join(exprs)})"

    def visit_between_expr(self, node: ast.BetweenExpr):
        op = super().visit_between_expr(node)

        nullable_expr = self._is_nullable(node.expr)
        nullable_low = self._is_nullable(node.low)
        nullable_high = self._is_nullable(node.high)
        not_nullable = not nullable_expr and not nullable_low and not nullable_high

        if not_nullable:
            return op

        return f"ifNull({op}, 0)"

    def visit_constant(self, node: ast.Constant):
        if (
            node.value is None
            or isinstance(node.value, bool)
            or isinstance(node.value, int)
            or isinstance(node.value, float)
            or isinstance(node.value, UUID)
            or isinstance(node.value, UUIDT)
            or isinstance(node.value, datetime)
            or isinstance(node.value, date)
        ):
            # Inline some permitted types in ClickHouse
            value = self._print_escaped_string(node.value)
            if "%" in value:
                # We don't know if this will be passed on as part of a legacy ClickHouse query or not.
                # Ban % to be on the safe side. Who knows how it can end up in a UUID or datetime for example.
                raise QueryError(f"Invalid character '%' in constant: {value}")
            return value
        else:
            # Strings, lists, tuples, and any other random datatype printed in ClickHouse.
            return self.context.add_value(node.value)

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(map(str, node.chain))}")

        return self.visit(node.type)

    def _get_property_group_source_for_field(
        self, field_type: ast.FieldType, property_name: str
    ) -> PrintableMaterializedPropertyGroupItem | None:
        """
        Find a property group source for the given field and property name.
        Used for JSONHas optimizations where we specifically need property group sources
        (not mat_* columns) because property groups can efficiently check for key existence.
        """
        if self.context.modifiers.propertyGroupsMode not in (
            PropertyGroupsMode.ENABLED,
            PropertyGroupsMode.OPTIMIZED,
        ):
            return None

        field = field_type.resolve_database_field(self.context)
        table = field_type.table_type
        while isinstance(table, ast.TableAliasType) or isinstance(table, ast.VirtualTableType):
            table = table.table_type

        if not isinstance(table, ast.TableType):
            return None

        table_name = table.table.to_printed_clickhouse(self.context)
        if field is None or not isinstance(field, DatabaseField):
            return None
        field_name = cast(Union[Literal["properties"], Literal["person_properties"]], field.name)

        for property_group_column in property_groups.get_property_group_columns(table_name, field_name, property_name):
            return PrintableMaterializedPropertyGroupItem(
                self.visit(field_type.table_type),
                self._print_identifier(property_group_column),
                self.context.add_value(property_name),
            )

        return None

    def _get_optimized_property_group_call(self, node: ast.Call) -> str | None:
        """
        Returns a printed expression corresponding to the provided call, if the function is being applied to a property
        group value and the function can be rewritten so that it can be eligible for use by the property group's map's
        key bloom filter index, or can be optimized to avoid reading the property group's map ``values`` subcolumn.
        """
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        # XXX: A lot of this is duplicated (sometimes just copy/pasted) from the null equality comparison logic -- it
        # might make sense to make it so that ``isNull``/``isNotNull`` is rewritten to comparison expressions before
        # this step, similar to how ``equals``/``notEquals`` are interpreted as their comparison operation counterparts.

        match node:
            case ast.Call(name="isNull" | "isNotNull" as function_name, args=[field]):
                # TODO: can probably optimize chained operations, but will need more thought
                field_type = resolve_field_type(field)
                if isinstance(field_type, ast.PropertyType) and len(field_type.chain) == 1:
                    property_source = self._get_materialized_property_source_for_property_type(field_type)
                    if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                        return None

                    match function_name:
                        case "isNull":
                            return f"not({property_source.has_expr})"
                        case "isNotNull":
                            return property_source.has_expr
                        case _:
                            raise ValueError(f"unexpected node name: {function_name}")
            case ast.Call(name="JSONHas", args=[field, ast.Constant(value=property_name)]):
                # TODO: can probably optimize chained operations here as well
                field_type = resolve_field_type(field)
                if not isinstance(field_type, ast.FieldType):
                    return None

                # TRICKY: Materialized property columns do not currently support null values (see comment in
                # `visit_property_type`) so checking whether or not a property is set for a row cannot safely use that
                # field and falls back to the equivalent ``JSONHas(properties, ...)`` call instead. However, if this
                # property is part of *any* property group, we can use that column instead to evaluate this expression
                # more efficiently -- even if the materialized column would be a better choice in other situations.
                if property_source := self._get_property_group_source_for_field(field_type, str(property_name)):
                    return property_source.has_expr

        return None  # nothing to optimize

    def _get_optimized_materialized_column_equals_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns an optimized printed expression for comparisons involving individually materialized columns.

        When comparing equality between a materialized column and a non-empty, non-null string constant, we can avoid the
        nullIf() wrapping that normally happens. This allows ClickHouse to use skip indexes on the materialized column.

        For example, instead of:
            ifNull(equals(nullIf(nullIf(events.`mat_$feature_flag`, ''), 'null'), 'some_value'), 0)
        We can emit:
            ifNull(equals(events.`mat_$feature_flag`, 'some_value'), 0)

        This is safe because we know 'some_value' is neither empty string nor 'null', so the nullIf
        checks are redundant for the comparison result. We keep the outer ifNull to ensure proper
        boolean semantics when composed with not() or other logical operations.
        """
        if node.op not in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            return None

        property_type: ast.PropertyType | None = None
        constant_expr: ast.Constant | None = None

        if isinstance(node.right, ast.Constant):
            left_type = resolve_field_type(node.left)
            if isinstance(left_type, ast.PropertyType):
                property_type = left_type
                constant_expr = node.right
        elif isinstance(node.left, ast.Constant):
            right_type = resolve_field_type(node.right)
            if isinstance(right_type, ast.PropertyType):
                property_type = right_type
                constant_expr = node.left

        if property_type is None or constant_expr is None:
            return None

        # Only optimize simple property access (not chained like properties.foo.bar)
        if len(property_type.chain) != 1:
            return None

        # Only optimize for non-empty, non-null string constants
        if not isinstance(constant_expr.value, str):
            return None
        if constant_expr.value in MAT_COL_NULL_SENTINELS:
            return None

        # Check if this property uses an individually materialized column (not a property group)
        property_source = self._get_materialized_property_source_for_property_type(property_type)
        if not isinstance(property_source, PrintableMaterializedColumn):
            return None

        # These are optimized elsewhere
        if property_source.column.strip("`\"'") in COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING:
            return None

        # Build the optimized comparison using the raw materialized column
        materialized_column_sql = str(property_source)
        constant_sql = self.visit(constant_expr)

        # Wrap in additional handling to ensure proper boolean semantics when composed with not() or other logic.
        # - equals(NULL, 'value') → NULL, but should be 0 (false) so not() works correctly
        # - notEquals(NULL, 'value') → NULL, but should be 1 (true) since NULL != 'value'
        # Use a compound expression for the Eq case to allow skip indexes to be used (which are broken by ifNull)
        if node.op == ast.CompareOperationOp.Eq:
            if property_source.is_nullable:
                return (
                    f"(equals({materialized_column_sql}, {constant_sql}) AND ({materialized_column_sql} IS NOT NULL))"
                )
            else:
                return f"equals({materialized_column_sql}, {constant_sql})"
        else:
            if property_source.is_nullable:
                return f"ifNull(notEquals({materialized_column_sql}, {constant_sql}), 1)"
            else:
                return f"notEquals({materialized_column_sql}, {constant_sql})"

    def _get_optimized_materialized_column_ilike_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns an optimized printed expression for ILIKE comparisons involving materialized columns.

        For non-nullable columns with patterns that could match sentinel values ('', 'null'),
        we bail out and let the normal code path handle it with proper nullif wrapping.

        For patterns that cannot match sentinels, we use the raw materialized column directly,
        enabling skip index optimization.
        """
        if node.op not in (ast.CompareOperationOp.ILike, ast.CompareOperationOp.NotILike):
            return None

        property_type: ast.PropertyType | None = None
        pattern_expr: ast.Constant | None = None

        left_type = resolve_field_type(node.left)
        if isinstance(left_type, ast.PropertyType) and isinstance(node.right, ast.Constant):
            property_type = left_type
            pattern_expr = node.right

        if property_type is None or pattern_expr is None:
            return None

        # Only optimize simple property access (not chained like properties.foo.bar)
        if len(property_type.chain) != 1:
            return None

        # Only optimize for string pattern constants
        if not isinstance(pattern_expr.value, str):
            return None

        # Check if this property uses an individually materialized column (not a property group)
        property_source = self._get_materialized_property_source_for_property_type(property_type)
        if not isinstance(property_source, PrintableMaterializedColumn):
            return None

        materialized_column_sql = str(property_source)
        pattern_sql = self.visit(pattern_expr)

        if property_source.is_nullable:
            if node.op == ast.CompareOperationOp.ILike:
                if property_source.has_ngram_lower_index:
                    # Use the ngram_lower index if it exists, must use like instead of ilike.
                    # ilike(haystack, needle) is equivalent to like(lower(haystack), lower(needle)), though the latter is less CPU
                    # efficient so ONLY do this if the skip index is present.
                    # We use coalesce to match the index expression (ngram indexes don't support nullable columns).
                    return f"and(like(lower(coalesce({materialized_column_sql}, '')), lower({pattern_sql})), {materialized_column_sql} IS NOT NULL)"
                else:
                    # We include IS NOT NULL because we want to return FALSE rather than NULL if the column is NULL,
                    # and prefer this to wrapping in ifNull because it allows skip index usage.
                    return (
                        f"and(ilike({materialized_column_sql}, {pattern_sql}), {materialized_column_sql} IS NOT NULL)"
                    )
            else:
                # For NOT ILIKE, we need ifNull wrapper because NULL NOT ILIKE pattern should be TRUE.
                # We don't care about the skip index here, as bloom filters don't help with detecting negative presence
                return f"ifNull(notILike({materialized_column_sql}, {pattern_sql}), 1)"
        else:
            # Non-nullable columns store null values as the string 'null', so bail out of optimizing and let the
            # regular code path handle it, which handles this case
            if any(ilike_matches(pattern_expr.value, s) for s in MAT_COL_NULL_SENTINELS):
                return None

            if node.op == ast.CompareOperationOp.ILike:
                if property_source.has_ngram_lower_index:
                    return f"like(lower({materialized_column_sql}), lower({pattern_sql}))"
                else:
                    return f"ilike({materialized_column_sql}, {pattern_sql})"
            else:
                return f"notILike({materialized_column_sql}, {pattern_sql})"

    def _get_optimized_materialized_column_like_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns an optimized printed expression for LIKE comparisons involving materialized columns.

        For non-nullable columns with patterns that could match sentinel values ('', 'null'),
        we bail out and let the normal code path handle it with proper nullif wrapping.

        For patterns that cannot match sentinels, we use the raw materialized column directly,
        enabling skip index optimization. Unlike ILIKE, LIKE is case-sensitive which allows
        ClickHouse to use ngrambf_v1 skip indexes.
        """
        if node.op not in (ast.CompareOperationOp.Like, ast.CompareOperationOp.NotLike):
            return None

        property_type: ast.PropertyType | None = None
        pattern_expr: ast.Constant | None = None

        left_type = resolve_field_type(node.left)
        if isinstance(left_type, ast.PropertyType) and isinstance(node.right, ast.Constant):
            property_type = left_type
            pattern_expr = node.right

        if property_type is None or pattern_expr is None:
            return None

        # Only optimize simple property access (not chained like properties.foo.bar)
        if len(property_type.chain) != 1:
            return None

        # Only optimize for string pattern constants
        if not isinstance(pattern_expr.value, str):
            return None

        property_source = self._get_materialized_property_source_for_property_type(property_type)
        if not isinstance(property_source, PrintableMaterializedColumn):
            return None

        materialized_column_sql = str(property_source)

        if property_source.is_nullable:
            pattern_sql = self.visit(pattern_expr)
            if node.op == ast.CompareOperationOp.Like:
                # We include IS NOT NULL because we want to return FALSE rather than NULL if the column is NULL,
                # and prefer this to wrapping in ifNull because it allows skip index usage.
                return f"and(like({materialized_column_sql}, {pattern_sql}), {materialized_column_sql} IS NOT NULL)"
            else:  # NotLike
                # For NOT LIKE, we need ifNull wrapper because NULL NOT LIKE pattern should be TRUE
                return f"ifNull(notLike({materialized_column_sql}, {pattern_sql}), 1)"
        else:
            # Non-nullable columns store null values as the string 'null', so bail out of optimizing and let the
            # regular code path handle it, which handles this case
            if any(like_matches(pattern_expr.value, s) for s in MAT_COL_NULL_SENTINELS):
                return None
            pattern_sql = self.visit(pattern_expr)

            # For non-nullable columns with non-sentinel patterns, use raw column for performance
            if node.op == ast.CompareOperationOp.Like:
                return f"like({materialized_column_sql}, {pattern_sql})"
            else:  # NotLike
                return f"notLike({materialized_column_sql}, {pattern_sql})"

    def _get_optimized_materialized_column_in_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns an optimized printed expression for IN comparisons involving materialized columns.

        For non-nullable columns with values that could match sentinel values ('', 'null'),
        we bail out and let the normal code path handle it with proper nullif wrapping.

        For values that cannot match sentinels, we use the raw materialized column directly,
        enabling skip index optimization (bloom filter).
        """
        if node.op not in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            return None

        left_type = resolve_field_type(node.left)
        if not isinstance(left_type, ast.PropertyType):
            return None

        if len(left_type.chain) != 1:
            return None

        property_source = self._get_materialized_property_source_for_property_type(left_type)
        if not isinstance(property_source, PrintableMaterializedColumn):
            return None

        if property_source.column.strip("`\"'") in COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING:
            return None

        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            values: list[ast.Constant] = [node.right]
        elif isinstance(node.right, ast.Tuple) or isinstance(node.right, ast.Array):
            values = []
            for value in node.right.exprs:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    values.append(value)
                else:
                    return None
        else:
            return None

        if len(values) == 0:
            return None

        materialized_column_sql = str(property_source)

        if property_source.is_nullable:
            values_sql = ", ".join(self.visit(v) for v in values)
            if node.op == ast.CompareOperationOp.In:
                # We use transform_null_in=1 which makes it hard to use a skip index with the in() function in ClickHouse.
                # As a workaround, flip the args and use has() - this is safe because we already excluded NULL
                return f"and(has([{values_sql}], {materialized_column_sql}), {materialized_column_sql} IS NOT NULL)"
            else:
                return f"ifNull(notIn({materialized_column_sql}, tuple({values_sql})), 1)"
        else:
            # non-nullable materialized columns store NULL as 'null' or '', so bail out if the values contain this
            for value in values:
                if value.value in MAT_COL_NULL_SENTINELS:
                    return None
            values_sql = ", ".join(self.visit(v) for v in values)
            if node.op == ast.CompareOperationOp.In:
                return f"has([{values_sql}], {materialized_column_sql})"
            else:
                return f"notIn({materialized_column_sql}, tuple({values_sql}))"

    def _optimize_in_with_string_values(
        self, values: list[ast.Expr], property_source: PrintableMaterializedPropertyGroupItem
    ) -> str | None:
        """
        Optimizes an IN comparison against a list of values for property group bloom filter usage.
        Returns the optimized expression string, or None if optimization is not possible.
        """
        # Bail on the optimisation if any value is not a Constant, is the empty string, is NULL, or is not a string
        for v in values:
            if not isinstance(v, ast.Constant):
                return None
            if v.value == "" or v.value is None or not isinstance(v.value, str):
                return None

        # IN with an empty set of values is always false
        if len(values) == 0:
            return "0"

        # A problem we run into here is that an expression like
        # in(events.properties_group_feature_flags['$feature/onboarding-use-case-selection'], ('control', 'test'))
        # does not hit the bloom filter on the key, so we need to modify the expression so that it does

        # If only one value, switch to equality operator. Expressions like this will hit the bloom filter for both keys and values:
        # events.properties_group_feature_flags['$feature/onboarding-use-case-selection'] = 'control'
        if len(values) == 1:
            return f"equals({property_source.value_expr}, {self.visit(values[0])})"

        # With transform_null_in=1 in SETTINGS (which we have by default), if there are several values, we need to
        # include a check for whether the key exists to hit the keys bloom filter.
        # Unlike the version WITHOUT mapKeys above, the following expression WILL hit the bloom filter:
        # and(has(mapKeys(properties_group_feature_flags), '$feature/onboarding-use-case-selection'),
        #     in(events.properties_group_feature_flags['$feature/onboarding-use-case-selection'], ('control', 'test')))
        # Note that we could add a mapValues to this to use the values bloom filter
        # TODO to profile whether we should add mapValues. Probably no for flags, yes for properties.
        values_tuple = ", ".join(self.visit(v) for v in values)
        return f"and({property_source.has_expr}, in({property_source.value_expr}, tuple({values_tuple})))"

    def _get_optimized_property_group_compare_operation(self, node: ast.CompareOperation) -> str | None:
        """
        Returns a printed expression corresponding to the provided compare operation, if one of the operands is part of
        a property group value and: the comparison can be rewritten so that it can be eligible for use by one or more
        the property group's bloom filter data skipping indices, or the expression can be optimized to avoid reading the
        property group's map ``values`` subcolumn when doing comparisons to NULL values.
        """
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None

        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            # For commutative operations, we can rewrite the expression with parameters in either order without
            # affecting the result.
            # NOTE: For now, this only works with comparisons to constant values directly since we need to know whether
            # or not the non-``PropertyType`` operand is ``NULL`` to be able to rewrite the expression to the correct
            # optimized version. This could be extended to support *any* non-``Nullable`` expression as well, so that
            # expressions which do not reference a field as part of the expression (and therefore can be resolved to a
            # constant value during the initial stages of query execution, e.g. ``lower(concat('X', 'Y'))`` ) can also
            # utilize the index. (The same applies to ``In`` comparisons below, too.)
            property_type: ast.PropertyType | None = None
            constant_expr: ast.Constant | None = None

            # TODO: This doesn't resolve aliases for the constant operand, so this does not comprehensively cover all
            # optimizable expressions, but that case seems uncommon enough to avoid for now.
            if isinstance(node.right, ast.Constant):
                left_type = resolve_field_type(node.left)
                if isinstance(left_type, ast.PropertyType):
                    property_type = left_type
                    constant_expr = node.right
            elif isinstance(node.left, ast.Constant):
                right_type = resolve_field_type(node.right)
                if isinstance(right_type, ast.PropertyType):
                    property_type = right_type
                    constant_expr = node.left

            # TODO: Chained properties could likely be supported here to at least use the keys index.
            if property_type is None or len(property_type.chain) > 1:
                return None
            else:
                assert constant_expr is not None  # appease mypy - if we got this far, we should have a constant

            property_source = self._get_materialized_property_source_for_property_type(property_type)
            if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                return None

            if node.op == ast.CompareOperationOp.Eq:
                if constant_expr.value is None:
                    # "IS NULL" can be interpreted as "does not exist in the map" -- this avoids unnecessarily reading
                    # the ``values`` subcolumn of the map.
                    return f"not({property_source.has_expr})"

                # Equality comparisons to boolean constants can skip NULL checks while maintaining our desired result
                # (i.e. comparisons with NULL evaluate to false) since the value expression will return an empty string
                # if the property doesn't exist in the map.
                if constant_expr.value is True:
                    return f"equals({property_source.value_expr}, 'true')"
                elif constant_expr.value is False:
                    return f"equals({property_source.value_expr}, 'false')"

                if isinstance(constant_expr.type, ast.StringType):
                    printed_expr = f"equals({property_source.value_expr}, {self.visit(constant_expr)})"
                    if constant_expr.value == "":
                        # If we're comparing to an empty string literal, we need to disambiguate this from the default value
                        # for the ``Map(String, String)`` type used for storing property group values by also ensuring that
                        # the property key is present in the map. If this is in a ``WHERE`` clause, this also ensures we can
                        # still use the data skipping index on keys, even though the values index cannot be used.
                        printed_expr = f"and({property_source.has_expr}, {printed_expr})"

                    return printed_expr

            elif node.op == ast.CompareOperationOp.NotEq:
                if constant_expr.value is None:
                    # "IS NOT NULL" can be interpreted as "does exist in the map" -- this avoids unnecessarily reading
                    # the ``values`` subcolumn of the map, and also allows us to use the data skipping index on keys.
                    return property_source.has_expr

        elif node.op in (ast.CompareOperationOp.In):
            # ``IN`` is _not_ commutative, so we only need to check the left side operand (in contrast with above.)
            left_type = resolve_field_type(node.left)
            if not isinstance(left_type, ast.PropertyType):
                return None

            # TODO: Chained properties could likely be supported here to at least use the keys index.
            if left_type is None or len(left_type.chain) > 1:
                return None

            property_source = self._get_materialized_property_source_for_property_type(left_type)
            if not isinstance(property_source, PrintableMaterializedPropertyGroupItem):
                return None

            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    # we can't optimize here, as the unoptimized version returns true if the key doesn't exist OR the value is null
                    return None
                if node.right.value == "":
                    # If the RHS is the empty string, we need to disambiguate it from the default value for missing keys.
                    return f"and({property_source.has_expr}, equals({property_source.value_expr}, {self.visit(node.right)}))"
                elif isinstance(node.right.type, ast.StringType):
                    return f"equals({property_source.value_expr}, {self.visit(node.right)})"
            elif isinstance(node.right, ast.Tuple) or isinstance(node.right, ast.Array):
                return self._optimize_in_with_string_values(node.right.exprs, property_source)
            else:
                # TODO: Alias types are not resolved here (similarly to equality operations above) so some expressions
                # are not optimized that possibly could be if we took that additional step to determine whether or not
                # they are references to Constant types.
                return None

        return None  # nothing to optimize

    def visit_compare_operation(self, node: ast.CompareOperation):
        # If either side of the operation is a property that is part of a property group, special optimizations may
        # apply here to ensure that data skipping indexes can be used when possible.
        if optimized_property_group_compare_operation := self._get_optimized_property_group_compare_operation(node):
            return optimized_property_group_compare_operation

        # When comparing an individually materialized column being compared to a string constant,
        # we can skip the nullIf wrapping to allow skip index usage.
        if optimized_materialized_column_compare := self._get_optimized_materialized_column_equals_operation(node):
            return optimized_materialized_column_compare
        if optimized_materialized_ilike := self._get_optimized_materialized_column_ilike_operation(node):
            return optimized_materialized_ilike
        if optimized_materialized_like := self._get_optimized_materialized_column_like_operation(node):
            return optimized_materialized_like
        if optimized_materialized_in := self._get_optimized_materialized_column_in_operation(node):
            return optimized_materialized_in

        in_join_constraint = any(isinstance(item, ast.JoinConstraint) for item in self.stack)
        left = self.visit(node.left)
        right = self.visit(node.right)
        nullable_left = self._is_nullable(node.left)
        nullable_right = self._is_nullable(node.right)
        not_nullable = not nullable_left and not nullable_right

        # :HACK: until the new type system is out: https://github.com/PostHog/posthog/pull/17267
        # If we add a ifNull() around `events.timestamp`, we lose on the performance of the index.
        if ("toTimeZone(" in left and (".timestamp" in left or "_timestamp" in left)) or (
            "toTimeZone(" in right and (".timestamp" in right or "_timestamp" in right)
        ):
            not_nullable = True
        hack_sessions_timestamp = (
            "fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(raw_sessions.session_id_v7, 80)), 1000))",
            "raw_sessions_v3.session_timestamp",
        )
        if left in hack_sessions_timestamp or right in hack_sessions_timestamp:
            not_nullable = True

        # :HACK: Prevent ifNull() wrapping for $ai_trace_id, $ai_session_id, and $ai_is_error to allow index usage
        # The materialized columns mat_$ai_trace_id, mat_$ai_session_id, and mat_$ai_is_error have bloom filter indexes for performance
        if any(col in left or col in right for col in COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING):
            not_nullable = True

        constant_lambda = None
        value_if_one_side_is_null = False
        value_if_both_sides_are_null = False

        op = self._get_compare_op(node.op, left, right)
        if node.op == ast.CompareOperationOp.Eq:
            constant_lambda = lambda left_op, right_op: left_op == right_op
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotEq:
            constant_lambda = lambda left_op, right_op: left_op != right_op
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Like:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotLike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.ILike:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotILike:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.In:
            return op
        elif node.op == ast.CompareOperationOp.NotIn:
            return op
        elif node.op == ast.CompareOperationOp.GlobalIn:
            pass
        elif node.op == ast.CompareOperationOp.GlobalNotIn:
            pass
        elif node.op == ast.CompareOperationOp.Regex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.IRegex:
            value_if_both_sides_are_null = True
        elif node.op == ast.CompareOperationOp.NotIRegex:
            value_if_one_side_is_null = True
        elif node.op == ast.CompareOperationOp.Gt:
            constant_lambda = lambda left_op, right_op: (
                left_op > right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.GtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op >= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.Lt:
            constant_lambda = lambda left_op, right_op: (
                left_op < right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.LtEq:
            constant_lambda = lambda left_op, right_op: (
                left_op <= right_op if left_op is not None and right_op is not None else False
            )
        elif node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            raise InternalHogQLError("Cohort operations should have been resolved before printing")
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {node.op.name}")

        # Try to see if we can take shortcuts

        # Can we compare constants?
        if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant) and constant_lambda is not None:
            return "1" if constant_lambda(node.left.value, node.right.value) else "0"

        # Special cases when we should not add any null checks
        if in_join_constraint or self.dialect == "hogql" or not_nullable:
            return op

        # Special optimization for "Eq" operator
        if (
            node.op == ast.CompareOperationOp.Eq
            or node.op == ast.CompareOperationOp.Like
            or node.op == ast.CompareOperationOp.ILike
        ):
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNull({left})"
                return f"ifNull({op}, 0)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNull({right})"
                return f"ifNull({op}, 0)"
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate

        # Special optimization for "NotEq" operator
        if (
            node.op == ast.CompareOperationOp.NotEq
            or node.op == ast.CompareOperationOp.NotLike
            or node.op == ast.CompareOperationOp.NotILike
        ):
            if isinstance(node.right, ast.Constant):
                if node.right.value is None:
                    return f"isNotNull({left})"
                return f"ifNull({op}, 1)"
            elif isinstance(node.left, ast.Constant):
                if node.left.value is None:
                    return f"isNotNull({right})"
                return f"ifNull({op}, 1)"
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"  # Worse case performance, but accurate

        # Return false if one, but only one of the two sides is a null constant
        if isinstance(node.right, ast.Constant) and node.right.value is None:
            # Both are a constant null
            if isinstance(node.left, ast.Constant) and node.left.value is None:
                return "1" if value_if_both_sides_are_null is True else "0"

            # Only the right side is null. Return a value only if the left side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"
        elif isinstance(node.left, ast.Constant) and node.left.value is None:
            # Only the left side is null. Return a value only if the right side doesn't matter.
            if value_if_both_sides_are_null == value_if_one_side_is_null:
                return "1" if value_if_one_side_is_null is True else "0"

        # No constants, so check for nulls in SQL
        if value_if_one_side_is_null is True and value_if_both_sides_are_null is True:
            return f"ifNull({op}, 1)"
        elif value_if_one_side_is_null is True and value_if_both_sides_are_null is False:
            return f"ifNull({op}, isNotNull({left}) or isNotNull({right}))"
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is True:
            return f"ifNull({op}, isNull({left}) and isNull({right}))"  # Worse case performance, but accurate
        elif value_if_one_side_is_null is False and value_if_both_sides_are_null is False:
            return f"ifNull({op}, 0)"
        else:
            raise ImpossibleASTError("Impossible")

    def visit_call(self, node: ast.Call):
        # If the argument(s) are part of a property group, special optimizations may apply here to ensure that data
        # skipping indexes can be used when possible.
        if optimized_property_group_call := self._get_optimized_property_group_call(node):
            return optimized_property_group_call

        return super().visit_call(node)

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        raise QueryError("Printing HogQLX tags is only supported in HogQL queries")

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        raise QueryError("Printing HogQLX tags is only supported in HogQL queries")

    def visit_table_type(self, type: ast.TableType):
        return type.table.to_printed_clickhouse(self.context)

    def visit_unresolved_field_type(self, type: ast.UnresolvedFieldType):
        raise QueryError(f"Unable to resolve field: {type.name}")

    def _print_identifier(self, name: str) -> str:
        return escape_clickhouse_identifier(name)

    def _print_escaped_string(
        self, name: float | int | str | list | tuple | datetime | date | UUID | UUIDT | None
    ) -> str:
        return escape_clickhouse_string(name, timezone=self._get_timezone())

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ):
        # :IMPORTANT: This assures a "team_id" where clause is present on every selected table.
        # Skip warehouse tables and tables with an explicit skip.
        if (
            not isinstance(table_type.table, DataWarehouseTable)
            and not isinstance(table_type.table, SavedQuery)
            and not isinstance(table_type.table, DANGEROUS_NoTeamIdCheckTable)
            and node_type is not None
        ):
            return team_id_guard_for_table(node_type, self.context)

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        sql = table_type.table.to_printed_clickhouse(self.context)

        # Edge case. If we are joining an s3 table, we must wrap it in a subquery for the join to work
        if isinstance(table_type.table, S3Table) and (
            node.next_join or node.join_type == "JOIN" or (node.join_type and node.join_type.startswith("GLOBAL "))
        ):
            sql = f"(SELECT * FROM {sql})"

        return sql

    def _print_select_columns(self, columns):
        # Gather all visible aliases, and/or the last hidden alias for each unique alias name.
        found_aliases: dict[str, ast.Alias] = {}
        for alias in reversed(columns):
            if isinstance(alias, ast.Alias):
                if not found_aliases.get(alias.alias, None) or not alias.hidden:
                    found_aliases[alias.alias] = alias

        columns_sql = []
        for column in columns:
            if isinstance(column, ast.Alias):
                # It's either a visible alias, or the last hidden alias with this name.
                if found_aliases.get(column.alias) == column:
                    if column.hidden:
                        # Make the hidden alias visible
                        column = cast(ast.Alias, clone_expr(column))
                        column.hidden = False
                    else:
                        # Always print visible aliases.
                        pass
                else:
                    # Non-unique hidden alias. Skip.
                    column = column.expr
            elif isinstance(column, ast.Call):
                with self.context.timings.measure("printer"):
                    column_alias = safe_identifier(
                        HogQLPrinter(
                            context=self.context,
                            dialect="hogql",
                        ).visit(column)
                    )
                column = ast.Alias(alias=column_alias, expr=column)
            columns_sql.append(self.visit(column))

        return columns_sql

    def _get_extra_select_clauses(
        self,
        node: ast.SelectQuery,
        is_top_level_query: bool,
        part_of_select_union: bool,
        is_last_query_in_union: bool,
        space: str,
    ) -> list[str]:
        clauses: list[str] = []

        if self.context.output_format and is_top_level_query and (not part_of_select_union or is_last_query_in_union):
            clauses.append(f"FORMAT{space}{self.context.output_format}")

        if node.settings is not None:
            settings = self._print_settings(node.settings)
            if settings is not None:
                clauses.append(settings)

        return clauses

    def _get_table_name(self, table: ast.TableType) -> str:
        return table.table.to_printed_clickhouse(self.context)
