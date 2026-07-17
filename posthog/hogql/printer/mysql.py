from collections.abc import Callable
from typing import ClassVar, Optional

from posthog.hogql import ast
from posthog.hogql.ast import AST
from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_mysql_table import DirectMySQLTable
from posthog.hogql.errors import ImpossibleASTError, QueryError
from posthog.hogql.escape_sql import escape_mysql_identifier
from posthog.hogql.printer.mysql_functions import (
    MYSQL_FUNCTION_HANDLERS_LOWER,
    MYSQL_FUNCTION_RENAMES_LOWER,
    MYSQL_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.printer.postgres import PostgresPrinter

_DATE_TRUNC_UNITS = {"second", "minute", "hour", "day", "week", "month", "quarter", "year"}

_TIMESTAMPDIFF_UNITS = {
    "second": "SECOND",
    "minute": "MINUTE",
    "hour": "HOUR",
    "day": "DAY",
    "week": "WEEK",
    "month": "MONTH",
    "quarter": "QUARTER",
    "year": "YEAR",
}

# CAST target mapping: HogQL/ClickHouse/Postgres-flavored type names → MySQL CAST types.
# MySQL CAST only accepts a small set of target types (SIGNED, UNSIGNED, CHAR, DOUBLE, ...).
_MYSQL_CAST_TYPES: dict[str, str] = {
    "text": "CHAR",
    "string": "CHAR",
    "varchar": "CHAR",
    "char": "CHAR",
    "character": "CHAR",
    "character varying": "CHAR",
    "uuid": "CHAR",
    "int": "SIGNED",
    "integer": "SIGNED",
    "bigint": "SIGNED",
    "smallint": "SIGNED",
    "tinyint": "SIGNED",
    "mediumint": "SIGNED",
    "signed": "SIGNED",
    "unsigned": "UNSIGNED",
    "bool": "SIGNED",
    "boolean": "SIGNED",
    "float": "DOUBLE",
    "double": "DOUBLE",
    "double precision": "DOUBLE",
    "real": "DOUBLE",
    "decimal": "DECIMAL",
    "numeric": "DECIMAL",
    "date": "DATE",
    "datetime": "DATETIME",
    "timestamp": "DATETIME",
    "time": "TIME",
    "json": "JSON",
    "binary": "BINARY",
}


class MySQLPrinter(PostgresPrinter):
    """Prints a HogQL AST as MySQL 8 SQL.

    Inherits the direct-connection scaffolding from ``PostgresPrinter`` (parameterized
    constants, no team_id guard, direct-table printing hooks) but replaces every piece of
    Postgres-specific SQL surface: backtick identifiers, REGEXP_LIKE instead of ``~``,
    CASE-wrapped aggregates instead of FILTER (WHERE ...), MySQL CAST targets, and
    date-function expansions instead of date_trunc.
    """

    DIALECT_NAME: ClassVar[HogQLDialect] = "mysql"
    DIALECT_LABEL: ClassVar[str] = "MySQL"

    def __init__(
        self,
        context: HogQLContext,
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, stack=stack, settings=settings, pretty=pretty)

    # --- dialect feature support -------------------------------------------------

    def _assert_qualify_supported(self) -> None:
        raise QueryError("QUALIFY is not supported in the MySQL dialect")

    def _assert_with_ties_supported(self) -> None:
        raise QueryError("WITH TIES is not supported in the MySQL dialect")

    def _dialect_error_suffix(self) -> str:
        return "in the MySQL dialect"

    def _validate_within_group_for_aggregation(self, node: ast.Call, func_meta) -> None:
        raise QueryError(f"Aggregation '{node.name}' (WITHIN GROUP) is not supported in the MySQL dialect")

    def visit_sample_expr(self, node: ast.SampleExpr) -> Optional[str]:
        raise QueryError("SAMPLE is not supported in the MySQL dialect")

    def visit_join_expr(self, node: ast.JoinExpr):
        if node.join_type is not None and "FULL" in node.join_type:
            raise QueryError("FULL JOIN is not supported in the MySQL dialect")
        return super().visit_join_expr(node)

    def visit_lambda(self, node: ast.Lambda):
        raise QueryError("Lambdas are not supported in the MySQL dialect")

    def visit_dict(self, node: ast.Dict):
        raise QueryError("Dicts are not supported in the MySQL dialect")

    def visit_array(self, node: ast.Array):
        return f"JSON_ARRAY({', '.join(self.visit(expr) for expr in node.exprs)})"

    # --- identifiers and tables ---------------------------------------------------

    def _print_identifier(self, name: str) -> str:
        if len(name) > 64 and "__" in name:
            name = self._truncate_identifier(name)
        return escape_mysql_identifier(name)

    def _print_table_sql(self, table) -> str:
        return self._print_table(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectMySQLTable):
            return table.to_printed_mysql(self.context)
        if hasattr(table, "to_printed_mysql"):
            return table.to_printed_mysql(self.context)
        # Same fallback as the Postgres printer: non-direct tables print their ClickHouse
        # name so field prefixes (`events.event`) render; the executor never routes a
        # query that actually reads them to a direct connection.
        return table.to_printed_clickhouse(self.context)

    # --- operators -----------------------------------------------------------------

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        # LIKE follows the connected database's collation (usually case-insensitive in
        # MySQL); ILIKE forces case-insensitivity explicitly. REGEXP_LIKE's 'c'/'i' flags
        # pin case sensitivity to match ClickHouse semantics regardless of collation.
        if op == ast.CompareOperationOp.ILike:
            return f"(LOWER({left}) LIKE LOWER({right}))"
        elif op == ast.CompareOperationOp.NotILike:
            return f"(LOWER({left}) NOT LIKE LOWER({right}))"
        elif op == ast.CompareOperationOp.Regex:
            return f"REGEXP_LIKE({left}, {right}, 'c')"
        elif op == ast.CompareOperationOp.NotRegex:
            return f"(NOT REGEXP_LIKE({left}, {right}, 'c'))"
        elif op == ast.CompareOperationOp.IRegex:
            return f"REGEXP_LIKE({left}, {right}, 'i')"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f"(NOT REGEXP_LIKE({left}, {right}, 'i'))"
        return super()._get_compare_op(op, left, right)

    def visit_is_distinct_from(self, node: ast.IsDistinctFrom):
        # MySQL has no IS [NOT] DISTINCT FROM; the null-safe equality operator covers both.
        left = self._visit_infix_operand(node.left)
        right = self._visit_infix_operand(node.right)
        if node.negated:
            return f"({left} <=> {right})"
        return f"(NOT ({left} <=> {right}))"

    def visit_arithmetic_operation(self, node):
        # `%` cannot appear in printed SQL (PyMySQL would treat it as a parameter
        # placeholder), so modulo renders as MOD(a, b).
        if node.op == ast.ArithmeticOperationOp.Mod:
            return f"MOD({self.visit(node.left)}, {self.visit(node.right)})"
        return super().visit_arithmetic_operation(node)

    def visit_tuple(self, node: ast.Tuple) -> str:
        values = [self.visit(expr) for expr in node.exprs]
        # MySQL has no single-column row constructor; parentheses act as grouping.
        return f"({', '.join(values)})"

    # --- casts ----------------------------------------------------------------------

    def _mysql_cast_type(self, type_name: str) -> str:
        normalized = type_name.strip().lower()
        mapped = _MYSQL_CAST_TYPES.get(normalized)
        if mapped is None:
            raise QueryError(f"Unsupported CAST target '{type_name}' in the MySQL dialect")
        return mapped

    def visit_type_cast(self, node):
        return f"CAST({self.visit(node.expr)} AS {self._mysql_cast_type(node.type_name)})"

    def visit_try_cast(self, node: ast.TryCast):
        raise QueryError("TRY_CAST is not allowed in the MySQL dialect")

    # --- function calls ---------------------------------------------------------------

    def _get_function_renames(self) -> dict[str, str]:
        return MYSQL_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return MYSQL_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return MYSQL_PASSTHROUGH_FUNCTIONS

    def visit_call(self, node: ast.Call):
        if node.name.lower() in {"percentile_cont", "percentile_disc"}:
            raise QueryError(f"Aggregation '{node.name}' is not supported in the MySQL dialect")

        if node.name == "dateDiff":
            return self._visit_date_diff(node)

        if node.name.lower() == "date_trunc":
            return self._visit_date_trunc(node)

        return super().visit_call(node)

    def _constant_string_arg(self, node: ast.Call, index: int, what: str) -> str:
        arg = node.args[index]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            raise QueryError(f"{node.name} requires a constant string {what} in the MySQL dialect")
        return arg.value.lower()

    def _visit_date_diff(self, node: ast.Call) -> str:
        if len(node.args) != 3:
            raise QueryError("dateDiff expects exactly 3 arguments in the MySQL dialect")
        unit = self._constant_string_arg(node, 0, "unit")
        ts_unit = _TIMESTAMPDIFF_UNITS.get(unit)
        if ts_unit is None:
            raise QueryError(f"Unsupported dateDiff unit '{unit}' in the MySQL dialect")
        start = self.visit(node.args[1])
        end = self.visit(node.args[2])
        return f"TIMESTAMPDIFF({ts_unit}, {start}, {end})"

    def _visit_date_trunc(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            raise QueryError("date_trunc expects exactly 2 arguments in the MySQL dialect")
        unit = self._constant_string_arg(node, 0, "unit")
        if unit not in _DATE_TRUNC_UNITS:
            raise QueryError(f"Unsupported date_trunc unit '{unit}' in the MySQL dialect")
        return self._render_start_of(unit, self.visit(node.args[1]))

    # --- date truncation ---------------------------------------------------------------

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        # MySQL has no date_trunc; expand each unit into native date functions.
        if unit == "second":
            return f"DATE_ADD(DATE({arg}), INTERVAL (HOUR({arg}) * 3600 + MINUTE({arg}) * 60 + SECOND({arg})) SECOND)"
        if unit == "minute":
            return f"DATE_ADD(DATE({arg}), INTERVAL (HOUR({arg}) * 60 + MINUTE({arg})) MINUTE)"
        if unit == "hour":
            return f"DATE_ADD(DATE({arg}), INTERVAL HOUR({arg}) HOUR)"
        if unit == "day":
            return f"CAST(DATE({arg}) AS DATETIME)"
        if unit == "week":
            if week_mode in {1, 3}:
                return f"DATE_SUB(DATE({arg}), INTERVAL WEEKDAY({arg}) DAY)"
            if week_mode == 0:
                return f"DATE_SUB(DATE({arg}), INTERVAL (DAYOFWEEK({arg}) - 1) DAY)"
            raise QueryError(f"Unsupported toStartOfWeek mode `{week_mode}` in the MySQL dialect")
        if unit == "month":
            return f"DATE_SUB(DATE({arg}), INTERVAL (DAYOFMONTH({arg}) - 1) DAY)"
        if unit == "quarter":
            return f"DATE_ADD(MAKEDATE(YEAR({arg}), 1), INTERVAL (QUARTER({arg}) - 1) QUARTER)"
        if unit == "year":
            return f"MAKEDATE(YEAR({arg}), 1)"
        if unit == "isoyear":
            jan4 = f"MAKEDATE(FLOOR(YEARWEEK({arg}, 3) / 100), 4)"
            return f"DATE_SUB({jan4}, INTERVAL WEEKDAY({jan4}) DAY)"
        raise ImpossibleASTError(f"Unknown date truncation unit: {unit}")

    def _render_minute_bucket(self, arg: str, bucket_size: int) -> str:
        return (
            f"DATE_ADD(DATE({arg}), "
            f"INTERVAL (HOUR({arg}) * 60 + FLOOR(MINUTE({arg}) / {bucket_size}) * {bucket_size}) MINUTE)"
        )

    # --- CTEs ----------------------------------------------------------------------------

    def visit_cte(self, node: ast.CTE):
        if node.materialized is not None:
            raise QueryError("MATERIALIZED CTE hints are not supported in the MySQL dialect")
        if node.using_key is not None:
            raise QueryError("USING KEY is not supported in the MySQL dialect")
        return super().visit_cte(node)

    # --- JSON property access -----------------------------------------------------------

    def _json_property_args(self, chain) -> list[str]:
        # Bind the whole JSON path as a single parameter; key escaping happens here in
        # Python rather than in SQL.
        segments: list[str] = []
        for link in chain:
            if isinstance(link, int):
                segments.append(f"[{link}]")
            else:
                escaped = str(link).replace("\\", "\\\\").replace('"', '\\"')
                segments.append(f'."{escaped}"')
        return [self.context.add_value("$" + "".join(segments))]

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        if len(unsafe_args) == 0:
            return unsafe_field
        return f"JSON_UNQUOTE(JSON_EXTRACT({unsafe_field}, {unsafe_args[0]}))"
