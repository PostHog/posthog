from collections.abc import Callable
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)


class TrinoPrinter(PostgresPrinter):
    DIALECT_NAME: ClassVar[HogQLDialect] = "trino"
    DIALECT_LABEL: ClassVar[str] = "Trino"

    def _print_identifier(self, name: str) -> str:
        return escape_trino_identifier(name)

    def _get_function_renames(self) -> dict[str, str]:
        return TRINO_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return TRINO_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return TRINO_PASSTHROUGH_FUNCTIONS

    def _get_connection_supported_functions(self) -> set[str]:
        return set()

    def _print_table_sql(self, table) -> str:
        return self._print_table(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectTrinoTable):
            return table.to_printed_trino(self.context)
        if hasattr(table, "to_printed_trino"):
            return table.to_printed_trino(self.context)
        raise QueryError(f"Table '{table.name or table.__class__.__name__}' has no Trino physical locator.")

    def visit_lambda(self, node: ast.Lambda) -> str:
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if not identifiers:
            raise QueryError("Lambdas require at least one argument in Trino mode.")
        arguments = identifiers[0] if len(identifiers) == 1 else f"({', '.join(identifiers)})"
        return f"{arguments} -> {self.visit(node.expr)}"

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.Regex:
            return f"regexp_like({left}, {right})"
        if op == ast.CompareOperationOp.IRegex:
            return f"regexp_like({left}, '(?i)' || {right})"
        if op == ast.CompareOperationOp.NotRegex:
            return f"(NOT regexp_like({left}, {right}))"
        if op == ast.CompareOperationOp.NotIRegex:
            return f"(NOT regexp_like({left}, '(?i)' || {right}))"
        return super()._get_compare_op(op, left, right)

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        if unit == "week" and week_mode == 0:
            return f"date_add('day', -1, date_trunc('week', date_add('day', 1, {arg})))"
        if unit == "week" and week_mode not in {1, 3}:
            raise QueryError(f"Unsupported toStartOfWeek mode `{week_mode}` in Trino mode.")
        if unit == "isoyear":
            raise QueryError("toStartOfISOYear is not supported in Trino mode.")
        return f"date_trunc('{unit}', {arg})"

    def _render_minute_bucket(self, arg: str, bucket_size: int) -> str:
        return (
            f"date_add('minute', CAST(floor(minute({arg}) / {bucket_size}) AS BIGINT) * {bucket_size}, "
            f"date_trunc('hour', {arg}))"
        )

    def visit_array_slice(self, node: ast.ArraySlice) -> str:
        if node.start_expr is None or node.end_expr is None:
            raise QueryError("Open-ended array slices are not supported in Trino mode.")
        start = self.visit(node.start_expr)
        end = self.visit(node.end_expr)
        return f"slice({self.visit(node.array)}, {start}, ({end}) - ({start}) + 1)"

    def visit_type_cast(self, node: ast.TypeCast) -> str:
        return f"CAST({self.visit(node.expr)} AS {self._trino_type(node.type_name)})"

    def visit_try_cast(self, node: ast.TryCast) -> str:
        return f"TRY_CAST({self.visit(node.expr)} AS {self._trino_type(node.type_name)})"

    def _trino_type(self, type_name: str) -> str:
        aliases = {
            "bool": "BOOLEAN",
            "boolean": "BOOLEAN",
            "date": "DATE",
            "datetime": "TIMESTAMP",
            "float": "DOUBLE",
            "float32": "REAL",
            "float64": "DOUBLE",
            "int": "BIGINT",
            "int8": "TINYINT",
            "int16": "SMALLINT",
            "int32": "INTEGER",
            "int64": "BIGINT",
            "string": "VARCHAR",
            "text": "VARCHAR",
            "uint8": "SMALLINT",
            "uint16": "INTEGER",
            "uint32": "BIGINT",
            "uuid": "UUID",
        }
        target = aliases.get(type_name.lower())
        if target is None:
            raise QueryError(f"Type '{type_name}' is not supported in Trino mode.")
        return target

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        if not unsafe_args:
            return unsafe_field
        if len(unsafe_args) != 1:
            raise QueryError("Nested JSON property access must be lowered before Trino printing.")
        return f"json_extract_scalar({unsafe_field}, {unsafe_args[0]})"

    def _json_property_args(self, chain) -> list[str]:
        escaped_members = [str(key).replace("\\", "\\\\").replace('"', '\\"') for key in chain]
        path = "$" + "".join(f'."{member}"' for member in escaped_members)
        return [self.context.add_value(path)]

    def _assert_qualify_supported(self) -> None:
        raise QueryError("QUALIFY must be lowered before Trino printing.")

    def _assert_with_ties_supported(self) -> None:
        raise QueryError("WITH TIES must be lowered before Trino printing.")

    def visit_cte(self, node: ast.CTE) -> str:
        if node.materialized is not None or node.using_key is not None:
            raise QueryError("CTE materialization hints and USING KEY are not supported in Trino mode.")
        return super().visit_cte(node)
