from collections.abc import Callable
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_snowflake_identifier
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.snowflake_functions import (
    SNOWFLAKE_FUNCTION_HANDLERS_LOWER,
    SNOWFLAKE_FUNCTION_RENAMES_LOWER,
    SNOWFLAKE_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.printer.types import JoinExprResponse

# Date parts accepted by dateDiff, inlined as a literal into DATEDIFF (allowlisted
# to keep the inlined value injection-safe).
_SNOWFLAKE_DATE_PARTS: frozenset[str] = frozenset(
    {"second", "minute", "hour", "day", "week", "month", "quarter", "year"}
)

# HogQL type names accepted by a `::` cast, mapped to Snowflake types. Mirrors the cast
# function handlers (toString → VARCHAR, toInt → BIGINT, …) so `x::String` and
# `toString(x)` agree. Unmapped names are rejected rather than emitted verbatim.
_SNOWFLAKE_CAST_TYPES: dict[str, str] = {
    "int": "BIGINT",
    "integer": "BIGINT",
    "int8": "BIGINT",
    "int16": "BIGINT",
    "int32": "BIGINT",
    "int64": "BIGINT",
    "uint8": "BIGINT",
    "uint16": "BIGINT",
    "uint32": "BIGINT",
    "uint64": "BIGINT",
    "float": "DOUBLE",
    "float32": "DOUBLE",
    "float64": "DOUBLE",
    "double": "DOUBLE",
    "real": "DOUBLE",
    "decimal": "DECIMAL",
    "numeric": "DECIMAL",
    "string": "VARCHAR",
    "text": "VARCHAR",
    "varchar": "VARCHAR",
    "char": "VARCHAR",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "datetime64": "TIMESTAMP",
    "timestamp": "TIMESTAMP",
    "uuid": "VARCHAR",
}

# ClickHouse/strftime format specifier → Snowflake TO_CHAR format element.
_STRFTIME_TO_SNOWFLAKE: dict[str, str] = {
    "Y": "YYYY",
    "y": "YY",
    "m": "MM",
    "d": "DD",
    "H": "HH24",
    "I": "HH12",
    "M": "MI",
    "S": "SS",
    "p": "AM",
    "F": "YYYY-MM-DD",
    "T": "HH24:MI:SS",
    "R": "HH24:MI",
}


class SnowflakePrinter(PostgresPrinter):
    """Prints a HogQL AST as Snowflake SQL."""

    DIALECT_NAME: ClassVar[HogQLDialect] = "snowflake"
    DIALECT_LABEL: ClassVar[str] = "Snowflake"

    def _print_table_sql(self, table) -> str:
        return self._print_table(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectSnowflakeTable):
            return table.to_printed_snowflake(self.context)
        if hasattr(table, "to_printed_snowflake"):
            return table.to_printed_snowflake(self.context)
        return super()._print_table(table)

    def _print_identifier(self, name: str) -> str:
        # Always double-quote. The base (Postgres) printer leaves simple lowercase identifiers
        # unquoted, but Snowflake folds unquoted names to uppercase — an unquoted lowercase column
        # would read a different column than the one resolved. Quoting pins the exact name, matching
        # how table names are printed.
        return escape_snowflake_identifier(name)

    # --- PIVOT / UNPIVOT
    #
    # Snowflake's `PIVOT (agg(value) FOR col IN (...))` / `UNPIVOT (value FOR name IN (cols))`
    # reference their columns by bare, unqualified name — a table-qualified `t.col` is a syntax
    # error inside the clause. While rendering the clause body we flip `_in_pivot_clause` so fields
    # print as their bare (still quoted) column name; the source table itself prints normally.

    _in_pivot_clause: bool = False

    def visit_field_type(self, type: ast.FieldType) -> str:
        if self._in_pivot_clause:
            resolved = type.resolve_database_field(self.context)
            name = resolved.name if isinstance(resolved, DatabaseField) else type.name
            return self._print_identifier(name)
        return super().visit_field_type(type)

    def _render_pivot_source(self, table: ast.Expr) -> str:
        if isinstance(table, ast.JoinExpr):
            return self._print_join_expr_chain(table)
        rendered = self.visit(table)
        return rendered.printed_sql if isinstance(rendered, JoinExprResponse) else rendered

    def visit_pivot_expr(self, node: ast.PivotExpr) -> str:
        if node.group_by:
            raise QueryError(f"PIVOT with an explicit GROUP BY is not supported {self._dialect_error_suffix()}.")
        table = self._render_pivot_source(node.table)
        previous, self._in_pivot_clause = self._in_pivot_clause, True
        try:
            aggregates = ", ".join(self.visit(agg) for agg in node.aggregates)
            columns = " ".join(self.visit(col) for col in node.columns)
        finally:
            self._in_pivot_clause = previous
        return f"{table} PIVOT ({aggregates} FOR {columns})"

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> str:
        table = self._render_pivot_source(node.table)
        include_nulls = "INCLUDE NULLS " if node.include_nulls else ""
        previous, self._in_pivot_clause = self._in_pivot_clause, True
        try:
            columns = " ".join(self.visit(col) for col in node.columns)
        finally:
            self._in_pivot_clause = previous
        return f"{table} UNPIVOT {include_nulls}({columns})"

    # --- Function Calls

    def _get_function_renames(self) -> dict[str, str]:
        return SNOWFLAKE_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return SNOWFLAKE_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return SNOWFLAKE_PASSTHROUGH_FUNCTIONS

    # --- ClickHouse-only SELECT clauses
    #
    # The inherited (base) visit_select_query emits these verbatim; Snowflake has no
    # equivalent, so reject loudly rather than emit SQL Snowflake can't run.

    def visit_select_query(self, node: ast.SelectQuery) -> str:
        if node.array_join_op is not None:
            raise QueryError(f"ARRAY JOIN is not supported {self._dialect_error_suffix()}.")
        if node.prewhere is not None:
            raise QueryError(f"PREWHERE is not supported {self._dialect_error_suffix()}.")
        if node.limit_by is not None:
            raise QueryError(f"LIMIT BY is not supported {self._dialect_error_suffix()}; use QUALIFY ROW_NUMBER().")
        return super().visit_select_query(node)

    def visit_sample_expr(self, node: ast.SampleExpr) -> str:
        # SAMPLE hangs off the table (JoinExpr), so reject it here rather than in the select query.
        raise QueryError(f"SAMPLE is not supported {self._dialect_error_suffix()}.")

    # --- Operators and literals
    #
    # Snowflake has no `~` regex operators, `[...]` array / `{...}` object literals, scalar
    # tuples, or `[a:b]` slices — translate the ones with a clean equivalent and reject the rest.

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        # match()-style "found anywhere" semantics (REGEXP_INSTR != 0), consistent with the
        # `match` function handler. The 6th arg 'i' makes the case-insensitive variants ignore case.
        if op == ast.CompareOperationOp.Regex:
            return f"(REGEXP_INSTR({left}, {right}) != 0)"
        if op == ast.CompareOperationOp.NotRegex:
            return f"(REGEXP_INSTR({left}, {right}) = 0)"
        if op == ast.CompareOperationOp.IRegex:
            return f"(REGEXP_INSTR({left}, {right}, 1, 1, 0, 'i') != 0)"
        if op == ast.CompareOperationOp.NotIRegex:
            return f"(REGEXP_INSTR({left}, {right}, 1, 1, 0, 'i') = 0)"
        return super()._get_compare_op(op, left, right)

    def visit_type_cast(self, node: ast.TypeCast) -> str:
        target = _SNOWFLAKE_CAST_TYPES.get(node.type_name.lower())
        if target is None:
            raise QueryError(f"Unsupported cast to type '{node.type_name}' {self._dialect_error_suffix()}.")
        return f"CAST({self.visit(node.expr)} AS {target})"

    def visit_array(self, node: ast.Array) -> str:
        return f"ARRAY_CONSTRUCT({', '.join(self.visit(expr) for expr in node.exprs)})"

    def visit_tuple(self, node: ast.Tuple) -> str:
        # HogQL lowers `{...}` object literals to a tagged tuple
        # (`'__hx_tag', '__hx_obj', key, value, …`) before printing — emit those as a
        # Snowflake OBJECT. Genuine scalar tuples have no Snowflake type, so reject them.
        exprs = node.exprs
        if (
            len(exprs) >= 2
            and isinstance(exprs[0], ast.Constant)
            and exprs[0].value == "__hx_tag"
            and isinstance(exprs[1], ast.Constant)
            and exprs[1].value == "__hx_obj"
        ):
            return f"OBJECT_CONSTRUCT({', '.join(self.visit(expr) for expr in exprs[2:])})"
        raise QueryError(f"Tuple expressions are not supported {self._dialect_error_suffix()}.")

    def visit_array_slice(self, node: ast.ArraySlice) -> str:
        raise QueryError(f"Array slices are not supported {self._dialect_error_suffix()}; use ARRAY_SLICE().")

    def visit_call(self, node: ast.Call) -> str:
        # dateDiff / formatDateTime can't be plain handlers: their first argument
        # (date part / format string) must be inlined as a literal, but by the time
        # a handler runs it has already been bound as a parameter. Intercept here,
        # where the raw AST Constant is still available.
        name = node.name.lower()
        if name == "datediff":
            return self._visit_date_diff(node)
        if name == "formatdatetime":
            return self._visit_format_datetime(node)
        return super().visit_call(node)

    def _visit_date_diff(self, node: ast.Call) -> str:
        if len(node.args) != 3:
            raise QueryError(f"dateDiff expects exactly 3 arguments {self._dialect_error_suffix()}.")
        unit_node = node.args[0]
        if not (isinstance(unit_node, ast.Constant) and isinstance(unit_node.value, str)):
            raise QueryError(f"dateDiff requires a literal unit {self._dialect_error_suffix()}.")
        unit = unit_node.value.lower()
        if unit not in _SNOWFLAKE_DATE_PARTS:
            raise QueryError(f"Unsupported dateDiff unit '{unit}' {self._dialect_error_suffix()}.")
        start = self.visit(node.args[1])
        end = self.visit(node.args[2])
        return f"DATEDIFF('{unit}', {start}, {end})"

    def _visit_format_datetime(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            raise QueryError(f"formatDateTime expects exactly 2 arguments {self._dialect_error_suffix()}.")
        format_node = node.args[1]
        if not (isinstance(format_node, ast.Constant) and isinstance(format_node.value, str)):
            raise QueryError(f"formatDateTime requires a literal format string {self._dialect_error_suffix()}.")
        snowflake_format = self._translate_strftime_format(format_node.value)
        time_sql = self.visit(node.args[0])
        # The format is inlined into a single-quoted SQL literal, so any `'` it carries (a literal
        # quote the user escaped as `''` in HogQL) must be re-escaped as `''` — otherwise it closes
        # the string early, breaking the query or allowing injection.
        escaped_format = snowflake_format.replace("'", "''")
        return f"TO_CHAR({time_sql}, '{escaped_format}')"

    def _translate_strftime_format(self, fmt: str) -> str:
        # Translate ClickHouse/strftime %-specifiers to Snowflake TO_CHAR elements.
        # Literal runs containing letters are double-quoted so Snowflake doesn't
        # parse them as format elements.
        out: list[str] = []
        literal: list[str] = []

        def flush_literal() -> None:
            if not literal:
                return
            text = "".join(literal)
            literal.clear()
            # Letters would be read as format elements, and a literal double-quote would
            # open a quoted section — both must sit inside a quoted block, with `"` escaped
            # as `""` rather than dropped.
            if any(ch.isalpha() or ch == '"' for ch in text):
                out.append('"' + text.replace('"', '""') + '"')
            else:
                out.append(text)

        index = 0
        while index < len(fmt):
            char = fmt[index]
            if char != "%":
                literal.append(char)
                index += 1
                continue
            if index + 1 >= len(fmt):
                raise QueryError(f"Trailing '%' in formatDateTime format {self._dialect_error_suffix()}.")
            specifier = fmt[index + 1]
            if specifier == "%":
                literal.append("%")
            elif specifier in _STRFTIME_TO_SNOWFLAKE:
                flush_literal()
                out.append(_STRFTIME_TO_SNOWFLAKE[specifier])
            else:
                raise QueryError(f"Unsupported formatDateTime specifier '%{specifier}' {self._dialect_error_suffix()}.")
            index += 2
        flush_literal()
        return "".join(out)

    # --- Date truncation (toStartOf*)
    #
    # The inherited _visit_to_start_of_call dispatch (arg validation, week-mode
    # selection) is fine; only the rendering differs. Postgres emits make_date()
    # for ISO year and `n * interval` for minute buckets — neither exists / works
    # in Snowflake.

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        if unit == "week":
            # DAYOFWEEKISO (Mon=1 … Sun=7) ignores the WEEK_START session param, so
            # the boundary is deterministic regardless of account configuration.
            if week_mode in {1, 3}:  # ISO / Monday-start
                return f"DATE_TRUNC('day', DATEADD('day', 1 - DAYOFWEEKISO({arg}), {arg}))"
            if week_mode == 0:  # Sunday-start
                return f"DATE_TRUNC('day', DATEADD('day', -(DAYOFWEEKISO({arg}) % 7), {arg}))"
            raise QueryError(f"Unsupported toStartOfWeek mode `{week_mode}` {self._dialect_error_suffix()}.")
        if unit == "isoyear":
            # Jan 4 is always in ISO week 1; the Monday of its week is the ISO year start.
            jan4 = f"DATE_FROM_PARTS(YEAROFWEEKISO({arg}), 1, 4)"
            return f"DATEADD('day', 1 - DAYOFWEEKISO({jan4}), {jan4})"
        return f"DATE_TRUNC('{unit}', {arg})"

    def _render_minute_bucket(self, arg: str, bucket_size: int) -> str:
        return f"TIME_SLICE({arg}, {bucket_size}, 'MINUTE')"

    # --- CTEs

    def visit_cte(self, node: ast.CTE):
        if node.materialized is not None:
            raise QueryError("MATERIALIZED CTE hints are not supported in the Snowflake dialect")
        if node.using_key is not None:
            raise QueryError("USING KEY is not supported in the Snowflake dialect")
        return super().visit_cte(node)
