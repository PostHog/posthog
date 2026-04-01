import re
import hashlib
from typing import Literal

from posthog.hogql import ast
from posthog.hogql.ast import AST
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.models import StructDatabaseField
from posthog.hogql.errors import ImpossibleASTError, QueryError
from posthog.hogql.escape_sql import escape_postgres_identifier
from posthog.hogql.printer.base import HogQLPrinter
from posthog.hogql.printer.postgres_functions import (
    POSTGRES_FUNCTION_HANDLERS_LOWER,
    POSTGRES_FUNCTION_RENAMES_LOWER,
    POSTGRES_PASSTHROUGH_FUNCTIONS,
)

# Regex for validating function names — only alphanumeric and underscores allowed.
# Prevents SQL injection via backtick-quoted identifiers in HogQL.
_SAFE_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresPrinter(HogQLPrinter):
    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["postgres"],
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty)
        self._truncated_identifiers: dict[str, str] = {}
        self._used_truncated_identifiers: set[str] = set()
        self._connection_supported_functions = self._get_connection_supported_functions()

    def visit_field(self, node: ast.Field):
        if node.type is None:
            field = ".".join([self._print_hogql_identifier_or_index(identifier) for identifier in node.chain])
            raise ImpossibleASTError(f"Field {field} has no type")

        if isinstance(node.type, ast.LazyJoinType) or isinstance(node.type, ast.VirtualTableType):
            raise QueryError(f"Can't select a table when a column is expected: {'.'.join(map(str, node.chain))}")

        return self.visit(node.type)

    def visit_keyword(self, node: ast.Keyword):
        if not node.name.isidentifier():
            raise QueryError(f"Invalid keyword name: {node.name}")
        return node.name.upper()

    def visit_call(self, node: ast.Call):
        if node.name.lower() in {"percentile_cont", "percentile_disc"}:
            return super().visit_call(node)

        if node.name in {
            "toStartOfSecond",
            "toStartOfMinute",
            "toStartOfHour",
            "toStartOfDay",
            "toStartOfWeek",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
            "toStartOfISOYear",
        }:
            return self._visit_to_start_of_call(node)

        if node.name in {"toStartOfFiveMinutes", "toStartOfTenMinutes", "toStartOfFifteenMinutes"}:
            if len(node.args) != 1:
                raise QueryError(f"{node.name} expects exactly 1 argument in Postgres mode.")
            minute_bucket_sizes: dict[str, int] = {
                "toStartOfFiveMinutes": 5,
                "toStartOfTenMinutes": 10,
                "toStartOfFifteenMinutes": 15,
            }
            bucket_arg = self.visit(node.args[0])
            bucket_size = minute_bucket_sizes[node.name]
            return (
                f"date_trunc('hour', {bucket_arg}) + "
                f"(floor(extract(minute from {bucket_arg}) / {bucket_size})::int * {bucket_size} * interval '1 minute')"
            )

        if node.order_by:
            # ORDER BY in function calls is only supported for passthrough functions.
            func_name = node.name.lower()
            if (
                func_name not in POSTGRES_PASSTHROUGH_FUNCTIONS
                and func_name not in POSTGRES_FUNCTION_HANDLERS_LOWER
                and func_name not in POSTGRES_FUNCTION_RENAMES_LOWER
            ):
                raise QueryError(f"Function '{node.name}' does not support ORDER BY in the Postgres dialect.")

        # Validate function name characters to prevent SQL injection via
        # backtick-quoted identifiers that can contain arbitrary characters.
        if not _SAFE_FUNCTION_NAME_RE.match(node.name):
            raise QueryError(f"Unsupported function call '{node.name}': function name contains invalid characters.")

        args = [self.visit(arg) for arg in node.args]
        order_by_part = f" ORDER BY {', '.join(self.visit(o) for o in node.order_by)}" if node.order_by else ""

        func_name = node.name.lower()

        handler = POSTGRES_FUNCTION_HANDLERS_LOWER.get(func_name)
        if handler is not None:
            if node.order_by:
                raise QueryError(f"Function '{node.name}' does not support ORDER BY in the Postgres dialect.")
            return handler(args)

        pg_name = POSTGRES_FUNCTION_RENAMES_LOWER.get(func_name)
        if pg_name is not None:
            return f"{pg_name}({', '.join(args)}{order_by_part})"

        if func_name in POSTGRES_PASSTHROUGH_FUNCTIONS:
            return f"{func_name}({', '.join(args)}{order_by_part})"

        if func_name in self._connection_supported_functions:
            # Use the validated name — never the raw node.name
            return f"{func_name}({', '.join(args)})"

        raise QueryError(f"Function '{node.name}' is not supported in the Postgres dialect.")

    def visit_array_slice(self, node: ast.ArraySlice):
        start = self.visit(node.start_expr) if node.start_expr is not None else ""
        end = self.visit(node.end_expr) if node.end_expr is not None else ""
        return f"{self.visit(node.array)}[{start}:{end}]"

    def visit_try_cast(self, node: ast.TryCast):
        return f"TRY_CAST({self.visit(node.expr)} AS {node.type_name})"

    def visit_lambda(self, node: ast.Lambda):
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if len(identifiers) == 0:
            raise ValueError("Lambdas require at least one argument")
        return f"lambda {', '.join(identifiers)}: {self.visit(node.expr)}"

    def _print_table_sql(self, table) -> str:
        if isinstance(table, DirectPostgresTable):
            return table.to_printed_postgres(self.context)
        return table.to_printed_clickhouse(self.context)

    def _get_connection_supported_functions(self) -> set[str]:
        metadata = self.context.direct_postgres_connection_metadata
        if not isinstance(metadata, dict):
            return set()

        available_functions = metadata.get("available_functions")
        if not isinstance(available_functions, list):
            return set()

        return {
            function_name.lower()
            for function_name in available_functions
            if isinstance(function_name, str) and _SAFE_FUNCTION_NAME_RE.match(function_name)
        }

    def _visit_to_start_of_call(self, node: ast.Call) -> str:
        if len(node.args) == 0:
            raise QueryError(f"{node.name} expects at least 1 argument in Postgres mode.")

        truncated_arg = self.visit(node.args[0])

        if node.name in {
            "toStartOfSecond",
            "toStartOfMinute",
            "toStartOfHour",
            "toStartOfMonth",
            "toStartOfQuarter",
            "toStartOfYear",
        }:
            if len(node.args) != 1:
                raise QueryError(f"{node.name} expects exactly 1 argument in Postgres mode.")

            start_of_units: dict[str, str] = {
                "toStartOfSecond": "second",
                "toStartOfMinute": "minute",
                "toStartOfHour": "hour",
                "toStartOfMonth": "month",
                "toStartOfQuarter": "quarter",
                "toStartOfYear": "year",
            }
            return f"date_trunc('{start_of_units[node.name]}', {truncated_arg})"

        if node.name == "toStartOfDay":
            if len(node.args) == 1:
                return f"date_trunc('day', {truncated_arg})"
            raise QueryError("toStartOfDay with a timezone override is not supported in Postgres mode.")

        if node.name == "toStartOfWeek":
            if len(node.args) == 1:
                week_mode = 0 if self._get_week_start_day().name == "SUNDAY" else 3
            elif len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, int):
                week_mode = node.args[1].value
            else:
                raise QueryError("toStartOfWeek only supports literal week modes in Postgres mode.")

            if week_mode in {1, 3}:
                return f"date_trunc('week', {truncated_arg})"
            if week_mode == 0:
                return f"(date_trunc('week', ({truncated_arg} + interval '1 day')) - interval '1 day')"
            raise QueryError(f"Unsupported toStartOfWeek mode `{week_mode}` in Postgres mode.")

        if node.name == "toStartOfISOYear":
            if len(node.args) != 1:
                raise QueryError("toStartOfISOYear expects exactly 1 argument in Postgres mode.")

            return f"date_trunc('week', make_date(extract(isoyear from {truncated_arg})::int, 1, 4)::timestamp)"

        if len(node.args) != 1:
            raise QueryError(f"{node.name} expects exactly 1 argument in Postgres mode.")

        return f"date_trunc('day', {truncated_arg})"

    def visit_and(self, node):
        return f"({' AND '.join([f'({self.visit(expr)})' for expr in node.exprs])})"

    def visit_or(self, node):
        return f"({' OR '.join([f'({self.visit(expr)})' for expr in node.exprs])})"

    def visit_not(self, node):
        return f"(NOT {self.visit(node.expr)})"

    def visit_table_type(self, type: ast.TableType):
        return self._print_table(type.table)

    def _visit_in_values(self, node: ast.Expr) -> str:
        if isinstance(node, ast.Tuple):
            return f"({', '.join(self.visit(value) for value in node.exprs)})"
        elif isinstance(node, ast.Constant):
            return f"({self.visit(node)})"

        return self.visit(node)

    def visit_compare_operation(self, node: ast.CompareOperation):
        left = self.visit(node.left)

        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn):
            right = self._visit_in_values(node.right)
        else:
            right = self.visit(node.right)

        if (
            node.is_null_comparison_style
            and isinstance(node.right, ast.Constant)
            and node.right.value is None
            and node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq)
        ):
            not_kw = " NOT" if node.op == ast.CompareOperationOp.NotEq else ""
            return f"({left} IS{not_kw} NULL)"

        return self._get_compare_op(node.op, left, right)

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Eq:
            return f"({left} = {right})"
        elif op == ast.CompareOperationOp.NotEq:
            return f"({left} != {right})"
        elif op == ast.CompareOperationOp.Like:
            return f"({left} LIKE {right})"
        elif op == ast.CompareOperationOp.NotLike:
            return f"({left} NOT LIKE {right})"
        elif op == ast.CompareOperationOp.ILike:
            return f"({left} ILIKE {right})"
        elif op == ast.CompareOperationOp.NotILike:
            return f"({left} NOT ILIKE {right})"
        elif op == ast.CompareOperationOp.In:
            return f"({left} IN {right})"
        elif op == ast.CompareOperationOp.NotIn:
            return f"({left} NOT IN {right})"
        elif op == ast.CompareOperationOp.Regex:
            return f"({left} ~ {right})"
        elif op == ast.CompareOperationOp.NotRegex:
            return f"({left} !~ {right})"
        elif op == ast.CompareOperationOp.IRegex:
            return f"({left} ~* {right})"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f"({left} !~* {right})"
        elif op == ast.CompareOperationOp.Gt:
            return f"({left} > {right})"
        elif op == ast.CompareOperationOp.GtEq:
            return f"({left} >= {right})"
        elif op == ast.CompareOperationOp.Lt:
            return f"({left} < {right})"
        elif op == ast.CompareOperationOp.LtEq:
            return f"({left} <= {right})"
        else:
            raise ImpossibleASTError(f"Unknown CompareOperationOp: {op.name}")

    def _print_table_ref(self, table_type: ast.TableType | ast.LazyTableType, node: ast.JoinExpr) -> str:
        return self._print_table(table_type.table)

    def _ensure_team_id_where_clause(
        self,
        table_type: ast.TableType | ast.LazyTableType,
        node_type: ast.TableOrSelectType,
    ):
        # Team ID filtering is not required for Postgres queries
        pass

    def _print_identifier(self, name: str) -> str:
        if len(name) > 63 and "__" in name:
            name = self._truncate_identifier(name)
        return escape_postgres_identifier(name)

    def _truncate_identifier(self, name: str) -> str:
        existing = self._truncated_identifiers.get(name)
        if existing:
            return existing

        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        suffix = f"_{digest}"
        prefix = name[: 63 - len(suffix)]
        candidate = f"{prefix}{suffix}"

        counter = 1
        while candidate in self._used_truncated_identifiers:
            counter_suffix = f"_{digest}_{counter}"
            candidate = f"{name[: 63 - len(counter_suffix)]}{counter_suffix}"
            counter += 1

        self._truncated_identifiers[name] = candidate
        self._used_truncated_identifiers.add(candidate)
        return candidate

    def _json_property_args(self, chain):
        return [self._print_escaped_string(name) for name in chain]

    def _print_table(self, table) -> str:
        if isinstance(table, DirectPostgresTable):
            return (
                f"{escape_postgres_identifier(table.postgres_schema)}."
                f"{escape_postgres_identifier(table.postgres_table_name)}"
            )
        return table.to_printed_clickhouse(self.context)

    def visit_property_type(self, type: ast.PropertyType):
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return super().visit_property_type(type)

        database_field = type.field_type.resolve_database_field(self.context)
        if isinstance(database_field, StructDatabaseField):
            struct_expr = self.visit(type.field_type)
            for link in type.chain:
                struct_expr = f"({struct_expr}).{self._print_identifier(str(link))}"
            return struct_expr

        return super().visit_property_type(type)

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        if len(unsafe_args) == 0:
            return unsafe_field

        json_expr = unsafe_field
        for arg in unsafe_args[:-1]:
            json_expr = f"({json_expr}) -> {arg}"

        return f"({json_expr}) ->> {unsafe_args[-1]}"

    def _print_select_columns(self, columns):
        columns_sql = []
        for column in columns:
            # Unwrap hidden aliases
            if (isinstance(column, ast.Alias)) and column.hidden:
                column = column.expr

            if isinstance(column, ast.Field) and isinstance(column.type, ast.PropertyType):
                alias_name = ".".join(map(str, column.chain))
                column = ast.Alias(alias=alias_name, expr=column)

            columns_sql.append(self.visit(column))
        return columns_sql

    def visit_arithmetic_operation(self, node):
        if node.op == ast.ArithmeticOperationOp.Add:
            return f"({self.visit(node.left)} + {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Sub:
            return f"({self.visit(node.left)} - {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mult:
            return f"({self.visit(node.left)} * {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Div:
            return f"({self.visit(node.left)} / {self.visit(node.right)})"
        elif node.op == ast.ArithmeticOperationOp.Mod:
            return f"({self.visit(node.left)} % {self.visit(node.right)})"
        else:
            raise ImpossibleASTError(f"Unknown ArithmeticOperationOp {node.op}")

    def visit_tuple(self, node: ast.Tuple) -> str:
        values = [self.visit(expr) for expr in node.exprs]

        if len(values) == 1:
            # Parentheses around a single value are just grouping in Postgres. Use ROW() to construct a 1-column tuple.
            return f"ROW({values[0]})"

        return f"({', '.join(values)})"

    def visit_type_cast(self, node):
        expr_sql = self.visit(node.expr)
        return f"CAST({expr_sql} AS {escape_postgres_identifier(node.type_name)})"

    def visit_cte(self, node: ast.CTE):
        materialization_hint = (
            "" if node.materialized is None else ("MATERIALIZED " if node.materialized else "NOT MATERIALIZED ")
        )

        if node.cte_type == "subquery":
            columns_sql = (
                "" if node.columns is None else f"({', '.join(self._print_identifier(col) for col in node.columns)})"
            )
            using_key_sql = (
                ""
                if node.using_key is None
                else f" USING KEY ({', '.join(self._print_identifier(col) for col in node.using_key)})"
            )
            return f"{self._print_identifier(node.name)}{columns_sql}{using_key_sql} AS {materialization_hint}{self.visit(node.expr)}"

        return super().visit_cte(node)
