import re
from datetime import date, datetime
from typing import ClassVar, cast
from uuid import UUID

from django.conf import settings as django_settings

from posthog.hogql import ast
from posthog.hogql.ast import AST, Constant, StringType
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    SavedQuery,
    StringJSONDatabaseField,
    StructDatabaseField,
)
from posthog.hogql.database.s3_table import DataWarehouseTable, S3Table
from posthog.hogql.database.schema.events import EVENTS_TABLE_TYPES
from posthog.hogql.errors import ImpossibleASTError, InternalHogQLError, QueryError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_json_subcolumn_identifier,
    escape_clickhouse_string,
    safe_identifier,
)
from posthog.hogql.functions import ADD_OR_NULL_DATETIME_FUNCTIONS, FIRST_ARG_DATETIME_FUNCTIONS
from posthog.hogql.functions.embed_text import resolve_embed_text
from posthog.hogql.functions.udfs import JSON_DROP_KEYS_CLICKHOUSE_NAME
from posthog.hogql.printer.base import BasePrinter, get_channel_definition_dict, resolve_field_type
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.type_system import parse_sql_runtime_type
from posthog.hogql.visitor import GetFieldsTraverser, clone_expr

from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION, EXCHANGE_RATE_DICTIONARY_NAME
from posthog.models.team.team import WeekStartDay
from posthog.models.utils import UUIDT


def _table_filter_type(table_type: ast.TableOrSelectType) -> ast.TableOrSelectType:
    if isinstance(table_type, ast.ColumnAliasedTableType):
        return ast.TableAliasType(alias=table_type.alias, table_type=table_type.table_type)
    return table_type


def team_id_guard_for_table(table_type: ast.TableOrSelectType, context: HogQLContext) -> ast.Expr:
    """Add a mandatory "and(team_id, ...)" filter around the expression."""
    if not context.team_id:
        raise InternalHogQLError("context.team_id not found")

    field_table_type = _table_filter_type(table_type)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["team_id"], type=ast.FieldType(name="team_id", table_type=field_table_type)),
        right=ast.Constant(value=context.team_id),
        type=ast.BooleanType(),
    )


def retention_floor_for_table(table_type: ast.TableOrSelectType, retention_months: int) -> ast.Expr:
    """Floor an events-table scan to ``timestamp > now() - toIntervalMonth(retention_months)``.

    Sibling to ``team_id_guard_for_table``: a mandatory, context-derived guard added at the lowest level on the
    events table, so the events-data-retention cap can't be bypassed by query-supplied date filters or modifiers.
    Uses a calendar-month interval so the boundary lands on the exact date (no leap-year / 365-day drift).
    """
    field_table_type = _table_filter_type(table_type)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Gt,
        left=ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=field_table_type)),
        right=ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Sub,
            left=ast.Call(name="now", args=[]),
            right=ast.Call(name="toIntervalMonth", args=[ast.Constant(value=retention_months)]),
        ),
        type=ast.BooleanType(),
    )


# The $ai_* properties whose materialized columns carry bloom-filter skip indexes. We read them bare — no nullIf/ifNull
# wrapping — so the index stays usable. Canonical set; ClickHouse property resolution imports it to make the same call.
AI_BLOOM_FILTER_PROPERTIES = {"$ai_trace_id", "$ai_session_id", "$ai_is_error"}

# Both the property name and its `mat_` column spelling, so visit_compare_operation can match either side of a comparison.
COLUMNS_WITH_HACKY_OPTIMIZED_NULL_HANDLING = {
    *AI_BLOOM_FILTER_PROPERTIES,
    *(f"mat_{prop}" for prop in AI_BLOOM_FILTER_PROPERTIES),
}

# The only string literals a `Constant(inline_sentinel=True)` is allowed to render inline (escaped, unparameterized): the
# fixed scrubbing markers property resolution emits — the nullIf ''/'null' sentinels, the quote-trim regex, and the
# 'true'/'false' the property-group map stores booleans as. The printer refuses to inline anything else, so the flag can
# never be turned into an unparameterized read of arbitrary (e.g. user-supplied) text.
# The last five are the structural literals of the dynamic-JSON property read (object-arm empty check,
# DateTime detection/ISO compensation, and JSON quoting) — fixed strings, inlined to keep the printed
# expression stable instead of burning four parameters per property read.
INLINE_SENTINEL_LITERALS = frozenset({"", "null", "true", "false", '^"|"$', "{}", "DateTime", " ", "T", '"'})


class ClickHousePrinter(BasePrinter):
    DIALECT_NAME: ClassVar[HogQLDialect] = "clickhouse"

    def visit_cte(self, node: ast.CTE):
        if node.materialized is False:
            raise ImpossibleASTError("ClickHouse does not support NOT MATERIALIZED CTEs")
        if node.using_key is not None:
            raise ImpossibleASTError(f"CTE USING KEY is not supported in the '{self.DIALECT_NAME}' dialect")

        if node.cte_type == "subquery":
            if node.columns is not None:
                raise NotImplementedError("CTE column name lists are not supported in this dialect")
            materialized = " MATERIALIZED" if node.materialized else ""
            return f"{self._print_identifier(node.name)} AS{materialized} {self.visit(node.expr)}"
        return f"{self.visit(node.expr)} AS {self._print_identifier(node.name)}"

    def _render_set_query_limit_percent(self, limit: ast.Expr, limit_str: str) -> str:
        return str(self._limit_percent_constant_value(limit))

    def _render_select_query_limit_clause(self, limit: ast.Expr, is_percent: bool) -> str:
        if not is_percent:
            return f"LIMIT {self.visit(limit)}"
        return f"LIMIT {self._limit_percent_constant_value(limit)}"

    def _limit_percent_constant_value(self, limit: ast.Expr) -> float:
        if not isinstance(limit, ast.Constant) or not isinstance(limit.value, (int, float)):
            raise QueryError("LIMIT percent with expressions is not supported in clickhouse dialect")
        return limit.value / 100

    def _validate_within_group_for_aggregation(self, node: ast.Call, func_meta) -> None:
        if node.within_group is not None:
            raise QueryError(f"Aggregation '{node.name}' with WITHIN GROUP is not supported in ClickHouse dialect")

    def _render_function_call(self, node: ast.Call, func_meta) -> str:
        args_count = len(node.args) - func_meta.passthrough_suffix_args_count
        node_args, passthrough_suffix_args = node.args[:args_count], node.args[args_count:]

        if node.name in FIRST_ARG_DATETIME_FUNCTIONS:
            args: list[str] = []
            for idx, arg in enumerate(node_args):
                if idx == 0:
                    if isinstance(arg, ast.Call) and arg.name in ADD_OR_NULL_DATETIME_FUNCTIONS:
                        args.append(f"assumeNotNull(toDateTime({self.visit(arg)}))")
                    else:
                        args.append(f"toDateTime({self.visit(arg)}, 'UTC')")
                else:
                    args.append(self.visit(arg))
        elif node.name == "concat":
            args = []
            for arg in node_args:
                if isinstance(arg, ast.Constant):
                    if arg.value is None:
                        args.append("''")
                    elif isinstance(arg.value, str):
                        args.append(self.visit(arg))
                    else:
                        args.append(f"toString({self.visit(arg)})")
                elif isinstance(arg, ast.Call) and arg.name == "toString":
                    if len(arg.args) == 1 and isinstance(arg.args[0], ast.Constant):
                        if arg.args[0].value is None:
                            args.append("''")
                        else:
                            args.append(self.visit(arg))
                    else:
                        args.append(f"ifNull({self.visit(arg)}, '')")
                else:
                    args.append(f"ifNull(toString({self.visit(arg)}), '')")
        elif node.name in ("JSONAllPaths", "toJSONString"):
            args = [self._visit_json_function_argument(arg) for arg in node_args]
        else:
            args = [self.visit(arg) for arg in node_args]

        # Some of these `isinstance` checks are here just to make our type system happy
        # We have some guarantees in place to ensure that the arguments are string/constants anyway
        # Here's to hoping Python's type system gets as smart as TS's one day
        if func_meta.suffix_args:
            for suffix_arg in func_meta.suffix_args:
                if len(passthrough_suffix_args) > 0:
                    if not all(isinstance(arg, ast.Constant) for arg in passthrough_suffix_args):
                        raise QueryError(
                            f"Suffix argument '{suffix_arg.value}' expects ast.Constant arguments, but got {', '.join([type(arg).__name__ for arg in passthrough_suffix_args])}"
                        )

                    suffix_arg_args_values = [
                        arg.value for arg in passthrough_suffix_args if isinstance(arg, ast.Constant)
                    ]

                    if isinstance(suffix_arg.value, str):
                        suffix_arg.value = suffix_arg.value.format(*suffix_arg_args_values)
                    else:
                        raise QueryError(
                            f"Suffix argument '{suffix_arg.value}' expects a string, but got {type(suffix_arg.value).__name__}"
                        )
                args.append(self.visit(suffix_arg))

        relevant_clickhouse_name = func_meta.clickhouse_name
        if func_meta.overloads:
            # Prefer concrete fields/calls: transforms can leave a call's
            # recorded arg_types stale after fields are rewritten.
            first_arg = node.args[0] if len(node.args) > 0 else None
            first_arg_was_alias = False
            while isinstance(first_arg, ast.Alias):
                first_arg_was_alias = True
                first_arg = first_arg.expr
            first_arg_constant_type = None
            if (
                first_arg is not None
                and first_arg.type is not None
                and (
                    first_arg_was_alias or isinstance(first_arg, ast.Call) or isinstance(first_arg.type, ast.FieldType)
                )
            ):
                first_arg_constant_type = first_arg.type.resolve_constant_type(self.context)
            elif isinstance(node.type, ast.CallType) and len(node.type.arg_types) > 0:
                first_arg_constant_type = node.type.arg_types[0]

            if first_arg_constant_type is not None:
                for (
                    overload_types,
                    overload_clickhouse_name,
                ) in func_meta.overloads:
                    if isinstance(first_arg_constant_type, overload_types):
                        relevant_clickhouse_name = overload_clickhouse_name
                        break  # Found an overload matching the first function org

        if func_meta.tz_aware:
            has_tz_override = len(node.args) == func_meta.max_args

            if not has_tz_override:
                args.append(self.visit(ast.Constant(value=self._get_timezone())))

            # If the datetime is in correct format, use optimal toDateTime, it's stricter but faster
            # and it allows CH to use index efficiently.
            if (
                relevant_clickhouse_name == "parseDateTime64BestEffortOrNull"
                and len(node.args) == 1
                and isinstance(node.args[0], Constant)
                and isinstance(node.args[0].type, StringType)
            ):
                relevant_clickhouse_name = "parseDateTime64BestEffort"
                pattern_with_microseconds_str = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}$"
                pattern_mysql_str = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
                if re.match(pattern_with_microseconds_str, node.args[0].value):
                    relevant_clickhouse_name = "toDateTime64"
                elif re.match(pattern_mysql_str, node.args[0].value) or re.match(
                    r"^\d{4}-\d{2}-\d{2}$", node.args[0].value
                ):
                    relevant_clickhouse_name = "toDateTime"
            if (
                relevant_clickhouse_name == "now64"
                and (len(node.args) == 0 or (has_tz_override and len(node.args) == 1))
            ) or (
                relevant_clickhouse_name
                in (
                    "parseDateTime64BestEffortOrNull",
                    "parseDateTime64BestEffortUSOrNull",
                    "parseDateTime64BestEffort",
                    "toDateTime64",
                )
                and (len(node.args) == 1 or (has_tz_override and len(node.args) == 2))
            ):
                # These two CH functions require a precision argument before timezone
                args = [*args[:-1], "6", *args[-1:]]

        if node.name == "toStartOfWeek" and len(node.args) == 1:
            # If week mode hasn't been specified, use the project's default.
            # For Monday-based weeks mode 3 is used (which is ISO 8601), for Sunday-based mode 0 (CH default)
            args.insert(1, WeekStartDay(self._get_week_start_day()).clickhouse_mode)

        if node.name == "trimLeft" and len(args) == 2:
            return f"trim(LEADING {args[1]} FROM {args[0]})"
        elif node.name == "trimRight" and len(args) == 2:
            return f"trim(TRAILING {args[1]} FROM {args[0]})"
        elif node.name == "trim" and len(args) == 2:
            return f"trim(BOTH {args[1]} FROM {args[0]})"

        params = [self.visit(param) for param in node.params] if node.params is not None else None
        params_part = f"({', '.join(params)})" if params is not None else ""
        order_by_part = f" ORDER BY {', '.join(self.visit(o) for o in node.order_by)}" if node.order_by else ""
        args_part = f"({', '.join(args)}{order_by_part})"
        filter_part = f" FILTER (WHERE {self.visit(node.filter_expr)})" if node.filter_expr else ""
        return f"{relevant_clickhouse_name}{params_part}{args_part}{filter_part}"

    def _render_posthog_function_call(self, node: ast.Call, func_meta) -> str:
        args = [self.visit(arg) for arg in node.args]

        if node.name == "embedText":
            return self.visit_constant(resolve_embed_text(self.context.team, node))
        elif node.name == "lookupDomainType":
            channel_dict = get_channel_definition_dict()
            return f"coalesce(dictGetOrNull('{channel_dict}', 'domain_type', (coalesce({args[0]}, ''), 'source')), dictGetOrNull('{channel_dict}', 'domain_type', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
        elif node.name == "lookupPaidSourceType":
            channel_dict = get_channel_definition_dict()
            return f"coalesce(dictGetOrNull('{channel_dict}', 'type_if_paid', (coalesce({args[0]}, ''), 'source')) , dictGetOrNull('{channel_dict}', 'type_if_paid', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
        elif node.name == "lookupPaidMediumType":
            channel_dict = get_channel_definition_dict()
            return f"dictGetOrNull('{channel_dict}', 'type_if_paid', (coalesce({args[0]}, ''), 'medium'))"
        elif node.name == "lookupOrganicSourceType":
            channel_dict = get_channel_definition_dict()
            return f"coalesce(dictGetOrNull('{channel_dict}', 'type_if_organic', (coalesce({args[0]}, ''), 'source')), dictGetOrNull('{channel_dict}', 'type_if_organic', (cutToFirstSignificantSubdomain(coalesce({args[0]}, '')), 'source')))"
        elif node.name == "lookupOrganicMediumType":
            channel_dict = get_channel_definition_dict()
            return f"dictGetOrNull('{channel_dict}', 'type_if_organic', (coalesce({args[0]}, ''), 'medium'))"
        elif node.name == "convertCurrency":
            # convertCurrency(from_currency, to_currency, amount, timestamp?)
            from_currency, to_currency, amount, *_rest = args
            date = args[3] if len(args) > 3 and args[3] else "today()"
            db = django_settings.CLICKHOUSE_DATABASE
            scale = EXCHANGE_RATE_DECIMAL_PRECISION
            # Build rate lookup expressions
            from_rate = f"dictGetOrDefault(`{db}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', {from_currency}, {date}, toDecimal64(0, {scale}))"
            to_rate = f"dictGetOrDefault(`{db}`.`{EXCHANGE_RATE_DICTIONARY_NAME}`, 'rate', {to_currency}, {date}, toDecimal64(0, {scale}))"
            # Use if() around divisor to avoid division by zero — with enable_analyzer=0, the old analyzer evaluates all branches regardless of condition.
            safe_from_rate = f"if({from_rate} = 0, toDecimal128(1, {scale}), {from_rate})"
            return f"if(equals({from_currency}, {to_currency}), toDecimal128({amount}, {scale}), if({from_rate} = 0, toDecimal128(0, {scale}), multiplyDecimal(divideDecimal(toDecimal128({amount}, {scale}), {safe_from_rate}), {to_rate})))"

        relevant_clickhouse_name = func_meta.clickhouse_name
        if "{}" in relevant_clickhouse_name:
            if len(args) != 1:
                raise QueryError(f"Function '{node.name}' requires exactly one argument")
            return relevant_clickhouse_name.format(args[0])

        params = [self.visit(param) for param in node.params] if node.params is not None else None
        params_part = f"({', '.join(params)})" if params is not None else ""
        args_part = f"({', '.join(args)})"
        return f"{relevant_clickhouse_name}{params_part}{args_part}"

    def visit(self, node: AST | None):
        if node is None:
            return ""
        response = super().visit(node)

        if len(self.stack) == 0 and self.settings:
            if not isinstance(node, ast.SelectQuery) and not isinstance(node, ast.SelectSetQuery):
                raise QueryError("Settings can only be applied to SELECT queries")
            merged = self._merge_table_top_level_settings(self.settings)
            printed = self._print_settings(merged)
            if printed is not None:
                response += " " + printed

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

    def visit_values_query(self, node: ast.ValuesQuery):
        raise QueryError("VALUES clause is not supported in ClickHouse dialect")

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
        # Opt-in inline rendering for the fixed scrubbing sentinels property resolution emits, so its AST-built scrub renders
        # identically to the `json_extract_trim_quotes` helper's inline string. Gated to a fixed allowlist: the flag is set
        # only internally, so a value outside it is a bug — refuse to inline it rather than emit unparameterized text.
        if node.inline_sentinel and isinstance(node.value, str):
            if node.value not in INLINE_SENTINEL_LITERALS:
                raise ImpossibleASTError(f"inline_sentinel set on a non-sentinel constant: {node.value!r}")
            return self._print_escaped_string(node.value)
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
            if node.is_sensitive:
                return self.context.add_sensitive_value(node.value)
            return self.context.add_value(node.value)

    def visit_interpolate_expr(self, node: ast.InterpolateExpr):
        # ClickHouse requires backtick-quoted column references in INTERPOLATE clauses
        printed_expr = self.visit(node.expr)
        quoted_expr = escape_clickhouse_identifier(printed_expr)
        if node.value is not None:
            return f"{quoted_expr} AS {self.visit(node.value)}"
        return quoted_expr

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(map(str, node.chain))}")

        return self.visit(node.type)

    def visit_field_type(self, type: ast.FieldType):
        field_sql = super().visit_field_type(type)
        field_sql = self._maybe_stringify_events_json_field(type, field_sql)
        return self._maybe_apply_json_drop_keys(type, field_sql)

    def _maybe_stringify_events_json_field(self, type: ast.FieldType, field_sql: str) -> str:
        serialized = self._serialize_events_json_field(type, field_sql)
        if serialized is not None:
            return serialized
        return field_sql

    def _serialize_events_json_field(self, type: ast.FieldType, field_sql: str) -> str | None:
        if not self.context.uses_new_events_schema():
            return None
        if getattr(self, "_json_function_argument_depth", 0) > 0:
            return None

        resolved_field = type.resolve_database_field(self.context)
        if not isinstance(resolved_field, StringJSONDatabaseField):
            return None
        if resolved_field.name not in ("properties", "person_properties"):
            return None
        if not isinstance(type.table_type, ast.BaseTableType):
            return None

        if not isinstance(type.table_type.resolve_database_table(self.context), EVENTS_TABLE_TYPES):
            return None

        # toJSONString on a JSON column emits default values for every declared-but-absent typed path.
        # Real JSON nulls cannot exist in the column, and typed path names are top-level, so dropping
        # those declared defaults from a single serialization reproduces the original document.
        filter_expr = self._events_json_serialized_pair_filter(resolved_field.name)
        return (
            "concat('{', arrayStringConcat("
            "arrayMap(kv -> concat(toJSONString(kv.1), ':', kv.2), "
            f"arrayFilter(kv -> {filter_expr}, JSONExtractKeysAndValuesRaw(toJSONString({field_sql})))"
            "), ','), '}')"
        )

    def _events_json_serialized_pair_filter(self, field_name: str) -> str:
        subcolumns = (
            EVENTS_PROPERTIES_JSON_SUBCOLUMNS if field_name == "properties" else PERSON_PROPERTIES_JSON_SUBCOLUMNS
        )
        array_keys = []
        map_keys = []
        for key, column_type in subcolumns.items():
            runtime_type = parse_sql_runtime_type(column_type)
            if runtime_type.family == "array":
                array_keys.append(key)
            elif runtime_type.family == "map":
                map_keys.append(key)

        filters = ["kv.2 != 'null'"]
        if array_keys:
            filters.append(f"NOT (kv.2 = '[]' AND has({self._clickhouse_string_array(array_keys)}, kv.1))")
        if map_keys:
            filters.append(f"NOT (kv.2 = '{{}}' AND has({self._clickhouse_string_array(map_keys)}, kv.1))")
        return " AND ".join(filters)

    def _clickhouse_string_array(self, values: list[str]) -> str:
        return "[" + ", ".join(escape_clickhouse_string(value) for value in values) + "]"

    def _serialize_to_json_string_call(self, node: ast.Call) -> str | None:
        if node.name != "toJSONString" or len(node.args) != 1:
            return None
        arg_type = resolve_field_type(node.args[0])
        if not isinstance(arg_type, ast.FieldType):
            return None
        field_sql = super().visit_field_type(arg_type)
        serialized = self._serialize_events_json_field(arg_type, field_sql)
        if serialized is None:
            return None
        return self._maybe_apply_json_drop_keys(arg_type, serialized)

    def _visit_json_function_argument(self, node: ast.Expr) -> str:
        depth = getattr(self, "_json_function_argument_depth", 0)
        self._json_function_argument_depth = depth + 1
        try:
            return self.visit(node)
        finally:
            self._json_function_argument_depth = depth

    def _maybe_apply_json_drop_keys(self, type: ast.FieldType, field_sql: str) -> str:
        """
        Wraps a StringJSONDatabaseField in JSONDropKeys() to strip restricted property keys
        when the raw JSON blob is selected directly (e.g., `SELECT properties FROM events`).
        """
        if not self.context.restricted_properties:
            return field_sql

        resolved_field = type.resolve_database_field(self.context)
        if not isinstance(resolved_field, StringJSONDatabaseField):
            return field_sql

        # Use the resolved DB column name, not ``type.name``. With column-alias table syntax
        # (``FROM events AS e(uuid, event, ..., p)``) the AST field name is the alias (``p``),
        # but ClickHouse resolves it back to the original column. Comparing ``type.name`` here
        # would incorrectly skip JSONDropKeys wrapping for the aliased ``properties`` column.
        # ``person_properties`` is the underlying DB column for ``EventsPersonSubTable.properties``
        # (PoE mode); it is also a JSON blob that must be stripped of restricted person-property keys.
        if resolved_field.name not in ("properties", "person_properties"):
            return field_sql

        keys_to_drop = restricted_property_keys_for_table_type(type.table_type, self.context)
        if not keys_to_drop:
            return field_sql

        keys_placeholder = self.context.add_sensitive_value(sorted(keys_to_drop))
        return f"{JSON_DROP_KEYS_CLICKHOUSE_NAME}({keys_placeholder})({field_sql})"

    def _get_events_session_id_table_type(self, node: ast.Expr) -> ast.BaseTableType | None:
        """If the expression resolves to $session_id on the events table, return the table type."""
        from posthog.hogql.database.schema.events import EventsTable

        expr_type = resolve_field_type(node)

        if isinstance(expr_type, ast.FieldType) and expr_type.name == "$session_id":
            table_type = expr_type.table_type
        elif (
            isinstance(expr_type, ast.PropertyType)
            and expr_type.chain == ["$session_id"]
            and expr_type.field_type.name == "properties"
        ):
            table_type = expr_type.field_type.table_type
        elif (
            isinstance(node, ast.JSONSubcolumnAccess)
            and node.keys == ["$session_id"]
            and isinstance(resolve_field_type(node.expr), ast.FieldType)
        ):
            field_type = cast(ast.FieldType, resolve_field_type(node.expr))
            if field_type.name != "properties":
                return None
            table_type = field_type.table_type
        else:
            return None

        original_table_type = table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
            return cast(ast.BaseTableType, original_table_type)
        return None

    def _get_optimized_session_id_compare_operation(self, node: ast.CompareOperation) -> str | None:
        """Rewrite $session_id comparisons against UUID constants to use the $session_id_uuid column."""
        op_name = {
            ast.CompareOperationOp.Eq: "equals",
            ast.CompareOperationOp.NotEq: "notEquals",
            ast.CompareOperationOp.In: "in",
            ast.CompareOperationOp.NotIn: "notIn",
        }.get(node.op)
        if op_name is None:
            return None

        session_id_table: ast.BaseTableType | None = None
        constants: list[ast.Constant] = []

        if table := self._get_events_session_id_table_type(node.left):
            session_id_table = table
            constants = self._extract_uuid_constants(node.right)
        elif node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            if table := self._get_events_session_id_table_type(node.right):
                session_id_table = table
                constants = self._extract_uuid_constants(node.left)

        if session_id_table is None or not constants:
            return None

        field_sql = f"{self.visit(session_id_table)}.{self._print_identifier('$session_id_uuid')}"
        wrapped = [f"toUInt128(accurateCastOrNull({self.visit(c)}, 'UUID'))" for c in constants]

        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq):
            return f"{op_name}({field_sql}, {wrapped[0]})"
        return f"{op_name}({field_sql}, tuple({', '.join(wrapped)}))"

    @staticmethod
    def _extract_uuid_constants(node: ast.Expr) -> list[ast.Constant]:
        """Extract UUID string constants from an expression. Returns empty list if any value is not a valid UUID."""
        if isinstance(node, ast.Constant):
            return [node] if UUIDT.is_valid_uuid(node.value) else []
        if isinstance(node, (ast.Tuple, ast.Array)):
            result: list[ast.Constant] = []
            for expr in node.exprs:
                if not isinstance(expr, ast.Constant) or not UUIDT.is_valid_uuid(expr.value):
                    return []
                result.append(expr)
            return result
        return []

    def _is_events_table_timestamp_field(self, node: ast.Expr) -> bool:
        traverser = GetFieldsTraverser(node)

        for field in traverser.fields:
            if isinstance(field.type, ast.FieldType):
                field_name = str(field.chain[-1]) if field.chain else ""

                # Check if field name is timestamp-like
                if not (field_name == "timestamp" or field_name.endswith("_timestamp")):
                    continue

                table_type = field.type.table_type
                while True:
                    if isinstance(table_type, ast.TableType):
                        table_name = table_type.table.to_printed_hogql()
                        if table_name in (
                            "events",
                            "raw_sessions",
                            "raw_sessions_v3",
                            "session_replay_events",
                            "raw_session_replay_events",
                        ):
                            return True
                        break
                    elif isinstance(table_type, (ast.LazyJoinType, ast.VirtualTableType)):
                        table_type = table_type.table_type
                    elif isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                        table_type = table_type.table_type
                    else:
                        break

        return False

    def visit_compare_operation(self, node: ast.CompareOperation):
        # $session_id comparisons optimize a real column (not a property), so they stay on the printer. Every
        # property-based skip-index rewrite (materialized column, property group) now runs in ClickHouse property
        # resolution, which emits the optimized form as AST before printing (see clickhouse_property_resolution.py).
        if optimized_session_id := self._get_optimized_session_id_compare_operation(node):
            return optimized_session_id

        in_join_constraint = any(isinstance(item, ast.JoinConstraint) for item in self.stack)
        # indexHint() is purely an optimizer directive — its result is always true,
        # so ifNull wrapping inside it is unnecessary and prevents index usage.
        in_index_hint = any(isinstance(item, ast.Call) and item.name == "indexHint" for item in self.stack)
        left = self.visit(node.left)
        right = self.visit(node.right)
        nullable_left = self._is_nullable(node.left)
        nullable_right = self._is_nullable(node.right)
        not_nullable = not nullable_left and not nullable_right

        # :HACK: until the new type system is out: https://github.com/PostHog/posthog/pull/17267
        # If we add a ifNull() around `events.timestamp`, we lose on the performance of the index.
        # Only apply this optimization to actual table timestamp fields, not CTE fields.
        if self._is_events_table_timestamp_field(node.left) or self._is_events_table_timestamp_field(node.right):
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
            # With transform_null_in=1, ClickHouse rewrites notIn() to notNullIn().
            # In Distributed aggregate plans this can make the coordinator expect
            # a pre-rewrite aggregate column name while shards return the rewritten
            # one, e.g. minIf(..., notIn(...)) vs minIf(..., notNullIn(...)).
            # Wrapping nullable NOT IN matches the existing nullable materialized
            # column path and preserves transform_null_in=1 semantics.
            if nullable_left and not not_nullable and not in_join_constraint and not in_index_hint:
                return f"ifNull({op}, 1)"
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
        if in_join_constraint or not_nullable or in_index_hint:
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

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        # ClickHouse's plain divide() derives a decimal result scale of (dividend_scale - divisor_scale).
        # When the divisor's scale exceeds the dividend's — e.g. a Decimal(38, 2) column divided by a
        # Decimal(38, 18) one — that underflows to a negative scale and the query errors out with
        # "Decimal result's scale is less than argument's one". divideDecimal derives a valid result scale
        # (the max of the two operand scales, computed at runtime) instead, mirroring the currency-conversion
        # path in _render_posthog_function_call which uses divideDecimal for the same reason.
        if node.op == ast.ArithmeticOperationOp.Div and self._both_operands_decimal(node):
            return f"divideDecimal({self.visit(node.left)}, {self.visit(node.right)})"
        return super().visit_arithmetic_operation(node)

    def _both_operands_decimal(self, node: ast.ArithmeticOperation) -> bool:
        if node.left.type is None or node.right.type is None:
            return False
        left_type = node.left.type.resolve_constant_type(self.context)
        right_type = node.right.type.resolve_constant_type(self.context)
        return isinstance(left_type, ast.DecimalType) and isinstance(right_type, ast.DecimalType)

    def visit_call(self, node: ast.Call):
        serialized = self._serialize_to_json_string_call(node)
        if serialized is not None:
            return serialized

        # Property-group call optimizations (isNull/isNotNull/JSONHas over a property-group key) now run in ClickHouse
        # property resolution, which rewrites them to the keys-index `has(group, key)` form before printing.
        # The type-name argument reaches ClickHouse's type parser verbatim, so bound it to
        # type names we can classify — mirroring the whitelist CAST already enforces.
        if node.name.lower() in ("accuratecast", "accuratecastornull"):
            type_arg = node.args[1] if len(node.args) > 1 else None
            if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
                raise QueryError(f"{node.name} requires a constant string type name as its second argument")
            if parse_sql_runtime_type(type_arg.value).family == "unknown":
                raise QueryError(f"Unsupported type in {node.name}: '{type_arg.value}'")

        return super().visit_call(node)

    def visit_array_slice(self, node: ast.ArraySlice):
        array_str = self.visit(node.array)
        start_str = self.visit(node.start_expr) if node.start_expr is not None else "1"
        if node.end_expr is None:
            return f"arraySlice({array_str}, {start_str})"

        end_str = self.visit(node.end_expr)
        length_str = f"plus(minus({end_str}, {start_str}), 1)"
        return f"arraySlice({array_str}, {start_str}, {length_str})"

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

    def _ensure_access_control_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ):
        """Add access control guard for system tables"""
        from posthog.hogql.database.postgres_table import PostgresTable
        from posthog.hogql.printer.access_control import build_access_control_guard

        if node_type is None:
            return None
        if not isinstance(table_type.table, PostgresTable):
            return None
        if not self.context.database or not self.context.database.user_access_control:
            return None

        # Only apply access control to tables registered under the system namespace
        system_node = self.context.database.tables.children.get("system")
        if not system_node or table_type.table.name not in system_node.children:
            return None

        if not table_type.table.primary_key:
            return None

        return build_access_control_guard(table_type.table, node_type, self.context)

    def _events_retention_floor(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType | None,
    ) -> ast.Expr | None:
        from posthog.hogql.database.schema.events import EventsTable

        months = self.context.events_retention_months
        if months is None or node_type is None or not isinstance(table_type, ast.TableType):
            return None
        if not isinstance(table_type.table, EventsTable):
            return None
        return retention_floor_for_table(node_type, months)

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        table = table_type.table
        if hasattr(table, "to_printed_clickhouse_table_ref"):
            use_logical_alias = not isinstance(node.type, (ast.TableAliasType, ast.ColumnAliasedTableType))
            sql = table.to_printed_clickhouse_table_ref(self.context, use_logical_alias=use_logical_alias)
        else:
            sql = table.to_printed_clickhouse(self.context)

        # The v3 Parquet reader crashes (NOT_FOUND_COLUMN_IN_BLOCK) when the analyzer moves a
        # computed predicate into the object-storage scan's PREWHERE. Wrap the read in a subquery
        # that disables PREWHERE locally, so the surrounding query (incl. MergeTree joins) keeps it.
        # See ClickHouse issue 80443.
        if isinstance(table, S3Table) and table.format in ("Parquet", "Delta", "DeltaS3Wrapper"):
            return f"(SELECT * FROM {sql} SETTINGS optimize_move_to_prewhere = 0)"

        # Edge case. If we are joining an s3 table, we must wrap it in a subquery for the join to work
        if isinstance(table, S3Table) and (
            node.next_join or node.join_type == "JOIN" or (node.join_type and node.join_type.startswith("GLOBAL "))
        ):
            sql = f"(SELECT * FROM {sql})"

        return sql

    def _print_select_columns(self, columns):
        def _alias_from_column_type(column: ast.Expr) -> str | None:
            column_type = getattr(column, "type", None)
            if isinstance(column_type, ast.FieldAliasType):
                return column_type.alias
            if isinstance(column_type, ast.FieldType):
                return column_type.name
            if isinstance(column_type, ast.ExpressionFieldType):
                return column_type.name
            return None

        # Gather all visible aliases, and/or the last hidden alias for each unique alias name.
        found_aliases: dict[str, ast.Alias] = {}
        for alias in reversed(columns):
            if isinstance(alias, ast.Alias):
                if not found_aliases.get(alias.alias, None) or not alias.hidden:
                    found_aliases[alias.alias] = alias

        columns_sql = []
        used_aliases: set[str] = set()
        for column in columns:
            printed_alias: str | None = None
            dropped_hidden_alias = False
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
                    printed_alias = column.alias
                else:
                    # Non-unique hidden alias. Skip.
                    dropped_hidden_alias = True
                    column = column.expr

            if printed_alias is None:
                printed_alias = _alias_from_column_type(column)

            if isinstance(column, ast.Call) and not dropped_hidden_alias:
                with self.context.timings.measure("printer"):
                    column_alias = safe_identifier(HogQLPrinter(context=self.context).visit(column))
                # ClickHouse rejects duplicate aliases for different expressions in the
                # same SELECT. This can happen after "*" expansion if a subquery already
                # exposes a generated expression name like `toDate(period_end)`.
                if column_alias not in used_aliases:
                    column = ast.Alias(alias=column_alias, expr=column)
                    printed_alias = column_alias
                else:
                    printed_alias = None
            columns_sql.append(self.visit(column))
            if printed_alias is not None:
                used_aliases.add(printed_alias)

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

        # When self.settings exists, table-level settings are merged in visit() instead
        merged = (
            self._merge_table_top_level_settings(node.settings)
            if is_top_level_query and not self.settings
            else node.settings
        )
        if merged is not None:
            printed = self._print_settings(merged)
            if printed is not None:
                clauses.append(printed)

        return clauses

    def _get_table_name(self, table: ast.TableType) -> str:
        return table.table.to_printed_clickhouse(self.context)

    def visit_property_type(self, type: ast.PropertyType) -> str:
        # Respect the joined-subquery projection: if the property has already been
        # projected through a subquery, defer to base which renders the subquery alias
        # correctly, rather than re-resolving against the original struct column.
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return super().visit_property_type(type)

        # Struct columns (e.g. Parquet structs from the data warehouse) are backed by a ClickHouse
        # Tuple, not a JSON string. Emit chained tupleElement() calls instead of JSONExtractRaw(),
        # which ClickHouse rejects on Tuple arguments. Closes #58480.
        database_field = type.field_type.resolve_database_field(self.context)
        if isinstance(database_field, StructDatabaseField):
            expr = self.visit(type.field_type)
            for link in type.chain:
                expr = f"tupleElement({expr}, {self.context.add_value(str(link))})"
            return expr

        return super().visit_property_type(type)

    def visit_json_subcolumn_access(self, node: ast.JSONSubcolumnAccess) -> str:
        if isinstance(node.expr, ast.Field) and isinstance(node.expr.type, ast.FieldType):
            expr = super().visit_field_type(node.expr.type)
        else:
            expr = self.visit(node.expr)
        for index, key in enumerate(node.keys):
            separator = ".^" if node.access_type == "sub_object" and index == 0 else "."
            expr = f"{expr}{separator}{escape_clickhouse_json_subcolumn_identifier(key)}"
        if node.value_type is not None:
            expr = f"{expr}.:{node.value_type}"
        return expr
