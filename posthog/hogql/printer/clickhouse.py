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
from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string
from posthog.hogql.printer.base import _Printer, resolve_field_type
from posthog.hogql.printer.types import PrintableMaterializedPropertyGroupItem

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


class ClickHousePrinter(_Printer):
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
        if self.dialect != "clickhouse":
            return None

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

    def visit_compare_operation(self, node: ast.CompareOperation):
        # If either side of the operation is a property that is part of a property group, special optimizations may
        # apply here to ensure that data skipping indexes can be used when possible.
        if optimized_property_group_compare_operation := self._get_optimized_property_group_compare_operation(node):
            return optimized_property_group_compare_operation

        # If either side is an individually materialized column being compared to a string constant,
        # we can skip the nullIf wrapping to allow skip index usage.
        if optimized_materialized_column_compare := self._get_optimized_materialized_column_compare_operation(node):
            return optimized_materialized_column_compare

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
        if (
            "mat_$ai_trace_id" in left
            or "mat_$ai_trace_id" in right
            or "mat_$ai_session_id" in left
            or "mat_$ai_session_id" in right
            or "mat_$ai_is_error" in left
            or "mat_$ai_is_error" in right
            or "$ai_trace_id" in left
            or "$ai_trace_id" in right
            or "$ai_session_id" in left
            or "$ai_session_id" in right
            or "$ai_is_error" in left
            or "$ai_is_error" in right
        ):
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
        # only used for hogql direct printing (no prepare called)
        elif node.op == ast.CompareOperationOp.InCohort:
            op = f"{left} IN COHORT {right}"
        # only used for hogql direct printing (no prepare called)
        elif node.op == ast.CompareOperationOp.NotInCohort:
            op = f"{left} NOT IN COHORT {right}"
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

    def _ensure_team_id_where_clause(self, table_type: ast.TableType, node_type: ast.TableOrSelectType | None):
        # :IMPORTANT: This assures a "team_id" where clause is present on every selected table.
        # Skip warehouse tables and tables with an explicit skip.
        if (
            not isinstance(table_type.table, DataWarehouseTable)
            and not isinstance(table_type.table, SavedQuery)
            and not isinstance(table_type.table, DANGEROUS_NoTeamIdCheckTable)
            and node_type is not None
        ):
            return team_id_guard_for_table(node_type, self.context)

    def _print_table_ref(self, table_type: ast.TableType, node: ast.JoinExpr) -> str:
        sql = table_type.table.to_printed_clickhouse(self.context)

        # Edge case. If we are joining an s3 table, we must wrap it in a subquery for the join to work
        if isinstance(table_type.table, S3Table) and (
            node.next_join or node.join_type == "JOIN" or (node.join_type and node.join_type.startswith("GLOBAL "))
        ):
            sql = f"(SELECT * FROM {sql})"

        return sql
