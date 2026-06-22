from collections.abc import Callable
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.errors import QueryError
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.snowflake_functions import (
    SNOWFLAKE_FUNCTION_HANDLERS_LOWER,
    SNOWFLAKE_FUNCTION_RENAMES_LOWER,
    SNOWFLAKE_PASSTHROUGH_FUNCTIONS,
)

# Date parts accepted by dateDiff, inlined as a literal into DATEDIFF (allowlisted
# to keep the inlined value injection-safe).
_SNOWFLAKE_DATE_PARTS: frozenset[str] = frozenset(
    {"second", "minute", "hour", "day", "week", "month", "quarter", "year"}
)

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
        if isinstance(table, DirectSnowflakeTable):
            return table.to_printed_snowflake(self.context)
        if hasattr(table, "to_printed_snowflake"):
            return table.to_printed_snowflake(self.context)
        return super()._print_table_sql(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectSnowflakeTable):
            return table.to_printed_snowflake(self.context)
        if hasattr(table, "to_printed_snowflake"):
            return table.to_printed_snowflake(self.context)
        return super()._print_table(table)

    # --- Function Calls

    def _get_function_renames(self) -> dict[str, str]:
        return SNOWFLAKE_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return SNOWFLAKE_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return SNOWFLAKE_PASSTHROUGH_FUNCTIONS

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
        return f"TO_CHAR({time_sql}, '{snowflake_format}')"

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
            if any(ch.isalpha() for ch in text):
                out.append('"' + text.replace('"', "") + '"')
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
            raise QueryError("MATERIALIZED CTE hints are not supported in the SnowFlake dialect")
        if node.using_key is not None:
            raise QueryError("USING KEY is not supported in the SnowFlake dialect")
        return super().visit_cte(node)
