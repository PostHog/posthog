import re
import json
from collections.abc import Callable, Iterable
from typing import Any, ClassVar
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import Table
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING
from posthog.hogql.printer.base import BasePrinter
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.printer.types import JoinExprResponse

from posthog.uuidt import UUIDT

_TRINO_SIMPLE_TYPES = {
    "bigint": "BIGINT",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "double": "DOUBLE",
    "double precision": "DOUBLE",
    "float": "DOUBLE",
    "int": "BIGINT",
    "int8": "BIGINT",
    "int16": "BIGINT",
    "int32": "BIGINT",
    "int64": "BIGINT",
    "integer": "INTEGER",
    "json": "JSON",
    "real": "REAL",
    "smallint": "SMALLINT",
    "string": "VARCHAR",
    "text": "VARCHAR",
    "timestamp": "TIMESTAMP",
    "timestamp with local time zone": "TIMESTAMP WITH TIME ZONE",
    "timestamp with time zone": "TIMESTAMP WITH TIME ZONE",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
    "tinyint": "TINYINT",
    "uint8": "SMALLINT",
    "uint16": "INTEGER",
    "uint32": "BIGINT",
    "uint64": "DECIMAL(20, 0)",
    "uuid": "UUID",
    "varbinary": "VARBINARY",
    "varchar": "VARCHAR",
}
_TRINO_PARAMETERIZED_TYPE_RE = re.compile(
    r"^(decimal|numeric|varchar|char|fixedstring|datetime64|timestamp)\s*\((\d+(?:\s*,\s*\d+)?)\)$", re.I
)

_TRINO_JOIN_TYPES = frozenset(
    {
        "JOIN",
        "INNER JOIN",
        "LEFT JOIN",
        "LEFT OUTER JOIN",
        "RIGHT JOIN",
        "RIGHT OUTER JOIN",
        "FULL JOIN",
        "FULL OUTER JOIN",
        "CROSS JOIN",
    }
)
_TRINO_WINDOW_FUNCTION_RENAMES = {
    "any": "arbitrary",
    "argmax": "max_by",
    "argmin": "min_by",
    "grouparray": "array_agg",
    "laginframe": "lag",
}
_TRINO_WINDOW_FUNCTIONS = frozenset(
    {
        "arbitrary",
        "array_agg",
        "avg",
        "count",
        "cume_dist",
        "dense_rank",
        "first_value",
        "lag",
        "last_value",
        "lead",
        "max",
        "max_by",
        "min",
        "min_by",
        "nth_value",
        "ntile",
        "percent_rank",
        "rank",
        "row_number",
        "sum",
    }
)
_TRINO_NO_FRAME_WINDOW_FUNCTIONS = frozenset(
    {"cume_dist", "dense_rank", "lag", "lead", "ntile", "percent_rank", "rank", "row_number"}
)
_TRINO_CONDITIONAL_WINDOW_FUNCTIONS = {
    "anyif": "arbitrary",
    "avgif": "avg",
    "countif": "count",
    "grouparrayif": "array_agg",
    "maxif": "max",
    "minif": "min",
    "sumif": "sum",
}
_TRINO_UNIQ_WINDOW_FUNCTIONS = frozenset({"countdistinct", "uniq", "uniqexact", "uniqif", "uniqexactif"})
_TRINO_COMPARISON_MAPPING = {name.lower(): operation for name, operation in HOGQL_COMPARISON_MAPPING.items()}
_TRINO_EXTRACT_FIELDS = frozenset(
    {
        "day",
        "day_of_week",
        "day_of_year",
        "dow",
        "doy",
        "hour",
        "minute",
        "month",
        "quarter",
        "second",
        "timezone_hour",
        "timezone_minute",
        "week",
        "year",
        "year_of_week",
        "yow",
    }
)


class TrinoPrinter(PostgresPrinter):
    DIALECT_NAME: ClassVar[HogQLDialect] = "trino"
    DIALECT_LABEL: ClassVar[str] = "Trino"

    def _get_connection_supported_functions(self) -> set[str]:
        return set()

    def _get_function_renames(self) -> dict[str, str]:
        return TRINO_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return TRINO_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return TRINO_PASSTHROUGH_FUNCTIONS

    def _render_group_by_all_clause(self) -> str:
        return "GROUP BY AUTO"

    def _assert_set_operator_supported(self, set_operator: str) -> None:
        if set_operator not in {
            "UNION DISTINCT",
            "UNION ALL",
            "INTERSECT DISTINCT",
            "INTERSECT ALL",
            "INTERSECT",
            "EXCEPT DISTINCT",
            "EXCEPT ALL",
            "EXCEPT",
        }:
            raise QueryError(f"{set_operator} is not supported in the 'trino' dialect")

    def _assert_qualify_supported(self) -> None:
        raise QueryError("QUALIFY is not supported in the Trino dialect")

    def _assert_with_ties_supported(self) -> None:
        return

    def _append_select_limit_and_offset(
        self, clauses: list[str | None], node: ast.SelectQuery, limit: ast.Expr | None
    ) -> None:
        if node.offset is not None:
            self._validate_row_count(node.offset, "OFFSET")
            clauses.append(f"OFFSET {self.visit(node.offset)} ROWS")
        if limit is None:
            return
        self._validate_row_count(limit, "LIMIT")
        if node.limit_percent:
            raise QueryError("LIMIT percent is not allowed in trino dialect")
        if node.limit_with_ties:
            if not node.order_by:
                raise QueryError("LIMIT WITH TIES requires ORDER BY in the Trino dialect")
            clauses.append(f"FETCH FIRST {self.visit(limit)} ROWS WITH TIES")
        else:
            clauses.append(f"LIMIT {self.visit(limit)}")

    def _append_set_limit_and_offset(self, sql: str, node: ast.SelectSetQuery) -> str:
        suffixes: list[str] = []
        if node.offset is not None:
            self._validate_row_count(node.offset, "OFFSET")
            suffixes.append(f"OFFSET {self.visit(node.offset)} ROWS")
        if node.limit is not None:
            self._validate_row_count(node.limit, "LIMIT")
            if node.limit_percent:
                raise QueryError("LIMIT percent is not allowed in trino dialect")
            if node.limit_with_ties:
                raise QueryError("WITH TIES is not supported on HogQL set queries in the Trino dialect")
            else:
                suffixes.append(f"LIMIT {self.visit(node.limit)}")
        separator = f"\n{self.indent(1)}" if self.pretty else " "
        return sql.rstrip() + separator + separator.join(suffixes) if suffixes else sql

    @staticmethod
    def _validate_row_count(value: ast.Expr, clause: str) -> None:
        if (
            not isinstance(value, ast.Constant)
            or isinstance(value.value, bool)
            or not isinstance(value.value, int)
            or value.value < 0
        ):
            raise QueryError(f"{clause} must be a non-negative integer in the Trino dialect")

    def visit_select_query(self, node: ast.SelectQuery) -> str:
        if node.array_join_op is not None:
            raise QueryError("ARRAY JOIN is not supported in the Trino dialect")
        if node.prewhere is not None:
            raise QueryError("PREWHERE is not supported in the Trino dialect")
        if node.limit_by is not None:
            raise QueryError("LIMIT BY is not supported in the Trino dialect")
        if node.interpolate is not None:
            raise QueryError("INTERPOLATE is not supported in the Trino dialect")
        return super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        if node.join_type is not None and node.join_type not in _TRINO_JOIN_TYPES:
            raise QueryError(f"Join type '{node.join_type}' is not supported in the Trino dialect")
        if node.constraint is not None and node.join_type in {None, "CROSS JOIN"}:
            raise QueryError(f"{node.join_type or 'FROM'} does not accept a join constraint in the Trino dialect")
        return super().visit_join_expr(node)

    def visit_order_expr(self, node: ast.OrderExpr) -> str:
        if node.with_fill is not None:
            raise QueryError("WITH FILL is not supported in the Trino dialect")
        return super().visit_order_expr(node)

    def visit_named_argument(self, node: ast.NamedArgument) -> str:
        raise QueryError("Named arguments are not supported in the Trino dialect")

    def visit_positional_ref(self, node: ast.PositionalRef) -> str:
        if not isinstance(node.index, int) or isinstance(node.index, bool) or node.index < 1:
            raise QueryError(f"Positional reference must be a positive integer, got {node.index}")
        return str(node.index)

    def visit_sample_expr(self, node: ast.SampleExpr) -> None:
        if node.sample_value.left.value == 1 and node.sample_value.right is None and node.offset_value is None:
            return None
        raise QueryError("SAMPLE is not supported in the Trino dialect")

    def visit_constant(self, node: ast.Constant) -> str:
        if node.value is None or isinstance(node.value, bool | int | float):
            return self._print_escaped_string(node.value)
        value = str(node.value) if isinstance(node.value, UUID | UUIDT) else node.value
        self.context.add_value(value)
        return "?"

    def _print_identifier(self, name: str) -> str:
        return escape_trino_identifier(name)

    def _print_table_sql(self, table: Table) -> str:
        return self._print_table(table)

    def _print_table(self, table: Table) -> str:
        if isinstance(table, DirectTrinoTable):
            return table.to_printed_trino(self.context)
        raise QueryError("Only direct Trino tables can be printed into Trino SQL")

    def visit_type_cast(self, node: ast.TypeCast) -> str:
        return f"CAST({self.visit(node.expr)} AS {self._render_type_name(node.type_name)})"

    def visit_try_cast(self, node: ast.TryCast) -> str:
        return f"TRY_CAST({self.visit(node.expr)} AS {self._render_type_name(node.type_name)})"

    def _render_type_name(self, type_name: str) -> str:
        normalized = " ".join(type_name.strip().lower().split())
        if normalized in _TRINO_SIMPLE_TYPES:
            return _TRINO_SIMPLE_TYPES[normalized]
        if normalized.startswith("array(") and normalized.endswith(")"):
            return f"ARRAY({self._render_type_name(normalized[6:-1])})"
        if normalized.startswith("nullable(") and normalized.endswith(")"):
            return self._render_type_name(normalized[9:-1])
        match = _TRINO_PARAMETERIZED_TYPE_RE.fullmatch(normalized)
        if match is not None:
            base, parameters = match.groups()
            values = [int(parameter.strip()) for parameter in parameters.split(",")]
            normalized_base = base.lower()
            if normalized_base in {"decimal", "numeric"}:
                precision = values[0]
                scale = values[1] if len(values) == 2 else 0
                if len(values) > 2 or not 1 <= precision <= 38 or not 0 <= scale <= precision:
                    raise QueryError(f"Type '{type_name}' is not supported in the Trino dialect")
                rendered_parameters = str(precision) if len(values) == 1 else f"{precision},{scale}"
                return f"DECIMAL({rendered_parameters})"
            if normalized_base in {"datetime64", "timestamp"}:
                if len(values) != 1 or not 0 <= values[0] <= 12:
                    raise QueryError(f"Type '{type_name}' is not supported in the Trino dialect")
                return f"TIMESTAMP({values[0]})"
            if len(values) != 1 or values[0] < 1:
                raise QueryError(f"Type '{type_name}' is not supported in the Trino dialect")
            rendered_base = "CHAR" if normalized_base == "fixedstring" else normalized_base.upper()
            return f"{rendered_base}({values[0]})"
        raise QueryError(f"Type '{type_name}' is not supported in the Trino dialect")

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> str:
        if node.op == ast.ArithmeticOperationOp.Div:
            return f"(CAST({self.visit(node.left)} AS DOUBLE) / {self.visit(node.right)})"
        return super().visit_arithmetic_operation(node)

    def visit_array(self, node: ast.Array) -> str:
        return f"ARRAY[{', '.join(self.visit(expr) for expr in node.exprs)}]"

    def visit_array_slice(self, node: ast.ArraySlice) -> str:
        array = self.visit(node.array)
        start = self.visit(node.start_expr) if node.start_expr is not None else "1"
        if node.end_expr is None:
            length = "2147483647"
        else:
            end = self.visit(node.end_expr)
            length = f"greatest(0, ({end}) - ({start}) + 1)"
        return f"slice({array}, {start}, {length})"

    def visit_tuple(self, node: ast.Tuple) -> str:
        if not node.exprs:
            raise QueryError("Empty tuple expressions are not supported in the Trino dialect")
        return f"ROW({', '.join(self.visit(expr) for expr in node.exprs)})"

    def visit_tuple_access(self, node: ast.TupleAccess) -> str:
        if node.index < 1:
            raise QueryError("Tuple positions must be positive in the Trino dialect")
        return f"({self.visit(node.tuple)})[{node.index}]"

    def visit_lambda(self, node: ast.Lambda) -> str:
        return BasePrinter.visit_lambda(self, node)

    def visit_call(self, node: ast.Call) -> str:
        function_name = node.name.lower()
        if function_name == "date_part":
            if (
                node.params is not None
                or node.within_group is not None
                or node.distinct
                or node.order_by
                or node.filter_expr is not None
            ):
                raise QueryError("date_part does not accept aggregate modifiers in the Trino dialect")
            if (
                len(node.args) != 2
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
                or node.args[0].value.lower() not in _TRINO_EXTRACT_FIELDS
            ):
                raise QueryError("date_part requires a supported literal field in the Trino dialect")
            return f"EXTRACT({node.args[0].value.upper()} FROM {self.visit(node.args[1])})"
        if node.params is not None:
            if (
                function_name in {"quantile", "quantileif"}
                and len(node.params) == 1
                and len(node.args) == (2 if function_name.endswith("if") else 1)
                and node.within_group is None
                and not node.distinct
                and not node.order_by
                and (node.filter_expr is None or not function_name.endswith("if"))
            ):
                rendered = f"approx_percentile({self.visit(node.args[0])}, {self.visit(node.params[0])})"
                condition = node.args[1] if function_name.endswith("if") else node.filter_expr
                if condition is not None:
                    rendered += f" FILTER (WHERE {self.visit(condition)})"
                return rendered
            if (
                function_name == "grouparrayif"
                and len(node.params) == 1
                and len(node.args) == 2
                and node.within_group is None
                and not node.distinct
                and not node.order_by
                and node.filter_expr is None
            ):
                rendered = (
                    f"slice(array_agg({self.visit(node.args[0])}) "
                    f"FILTER (WHERE {self.visit(node.args[1])}), 1, {self.visit(node.params[0])})"
                )
                return rendered
            raise QueryError(f"Parametric function '{node.name}' is not supported in the Trino dialect")
        if node.within_group is not None:
            raise QueryError(f"WITHIN GROUP is not supported for '{node.name}' in the Trino dialect")
        aggregation = find_hogql_aggregation(node.name)
        if aggregation is None:
            if node.distinct:
                raise QueryError(f"DISTINCT is only supported for aggregate functions in the Trino dialect")
            if node.order_by:
                raise QueryError(f"ORDER BY is only supported for aggregate functions in the Trino dialect")
            if node.filter_expr is not None:
                raise QueryError(f"FILTER is only supported for aggregate functions in the Trino dialect")
        elif node.filter_expr is not None and function_name.endswith("if"):
            raise QueryError(f"Function '{node.name}' cannot combine its If condition with FILTER in the Trino dialect")
        if function_name in _TRINO_COMPARISON_MAPPING:
            if len(node.args) != 2:
                raise QueryError(f"Comparison '{node.name}' requires exactly two arguments")
            return self.visit_compare_operation(
                ast.CompareOperation(
                    left=node.args[0],
                    right=node.args[1],
                    op=_TRINO_COMPARISON_MAPPING[function_name],
                )
            )
        if function_name == "todecimal":
            if (
                len(node.args) != 2
                or not isinstance(node.args[1], ast.Constant)
                or isinstance(node.args[1].value, bool)
                or not isinstance(node.args[1].value, int)
                or not 0 <= node.args[1].value <= 18
            ):
                raise QueryError("toDecimal requires a literal scale between 0 and 18 in the Trino dialect")
            return f"CAST({self.visit(node.args[0])} AS DECIMAL(18,{node.args[1].value}))"
        if function_name == "todatetime64":
            if len(node.args) not in {1, 2}:
                raise QueryError("toDateTime64 timezone overrides are not supported in the Trino dialect")
            precision = 3
            if len(node.args) == 2:
                precision_arg = node.args[1]
                if (
                    not isinstance(precision_arg, ast.Constant)
                    or isinstance(precision_arg.value, bool)
                    or not isinstance(precision_arg.value, int)
                    or not 0 <= precision_arg.value <= 12
                ):
                    raise QueryError("toDateTime64 requires a literal precision from 0 to 12 in the Trino dialect")
                precision = precision_arg.value
            return f"CAST({self.visit(node.args[0])} AS TIMESTAMP({precision}))"
        if function_name == "todatetime" and len(node.args) not in {1, 2}:
            raise QueryError("toDateTime expects a value and an optional timezone in the Trino dialect")
        if function_name == "tostring" and len(node.args) != 1:
            raise QueryError("toString expects exactly one argument in the Trino dialect")
        if function_name == "tupleelement":
            if (
                len(node.args) != 2
                or not isinstance(node.args[1], ast.Constant)
                or isinstance(node.args[1].value, bool)
                or not isinstance(node.args[1].value, int)
                or node.args[1].value < 1
            ):
                raise QueryError("tupleElement requires a positive literal position in the Trino dialect")
            return f"({self.visit(node.args[0])})[{node.args[1].value}]"
        if function_name == "md5" and len(node.args) == 1 and isinstance(node.args[0], ast.Alias):
            value = self.visit(node.args[0].expr)
            return f"to_hex(md5(to_utf8(CAST({value} AS VARCHAR))))"
        if node.args and isinstance(node.args[0].type, ast.ArrayType | ast.StringArrayType | ast.MapType):
            value = self.visit(node.args[0])
            if function_name == "length":
                return f"cardinality({value})"
            if function_name == "empty":
                return f"(COALESCE(cardinality({value}), 0) = 0)"
            if function_name == "notempty":
                return f"(COALESCE(cardinality({value}), 0) > 0)"
        json_call = self._visit_json_call(node)
        if json_call is not None:
            return json_call
        rendered = super().visit_call(node)
        if node.filter_expr is not None:
            rendered += f" FILTER (WHERE {self.visit(node.filter_expr)})"
        return rendered

    def visit_window_function(self, node: ast.WindowFunction) -> str:
        if node.args:
            raise QueryError(f"Parametric window function '{node.name}' is not supported in the Trino dialect")

        function_name = node.name.lower()
        exprs = [self.visit(expr) for expr in node.exprs or []]
        if function_name in _TRINO_CONDITIONAL_WINDOW_FUNCTIONS:
            if len(exprs) < 1:
                raise QueryError(f"Window function '{node.name}' requires a condition")
            target = _TRINO_CONDITIONAL_WINDOW_FUNCTIONS[function_name]
            arguments = exprs[:-1]
            if target == "count" and not arguments:
                call = f"count(*) FILTER (WHERE {exprs[-1]})"
            else:
                call = f"{target}({', '.join(arguments)}) FILTER (WHERE {exprs[-1]})"
        elif function_name in _TRINO_UNIQ_WINDOW_FUNCTIONS:
            conditional = function_name.endswith("if")
            arguments = exprs[:-1] if conditional else exprs
            if not arguments:
                raise QueryError(f"Window function '{node.name}' requires at least one value")
            distinct_value = arguments[0] if len(arguments) == 1 else f"ROW({', '.join(arguments)})"
            call = f"count(DISTINCT {distinct_value})"
            if conditional:
                call += f" FILTER (WHERE {exprs[-1]})"
        else:
            target = _TRINO_WINDOW_FUNCTION_RENAMES.get(function_name, function_name)
            if target not in _TRINO_WINDOW_FUNCTIONS:
                raise QueryError(f"Window function '{node.name}' is not supported in the Trino dialect")
            rendered_arguments = "*" if target == "count" and not exprs else ", ".join(exprs)
            call = f"{target}({rendered_arguments})"

        window_expr = self._window_expression(node)
        target_name = _TRINO_WINDOW_FUNCTION_RENAMES.get(function_name, function_name)
        if target_name in _TRINO_NO_FRAME_WINDOW_FUNCTIONS and window_expr is not None and window_expr.frame_method:
            raise QueryError(f"Window function '{node.name}' does not allow a window frame in the Trino dialect")
        if target_name in {"lag", "lead"} and (window_expr is None or not window_expr.order_by):
            raise QueryError(f"Window function '{node.name}' requires ORDER BY in the Trino dialect")

        if node.over_expr is not None:
            over = f"({self.visit(node.over_expr)})"
        elif node.over_identifier is not None:
            over = self._print_identifier(node.over_identifier)
        else:
            over = "()"
        return f"{call} OVER {over}"

    def _window_expression(self, node: ast.WindowFunction) -> ast.WindowExpr | None:
        if node.over_expr is not None:
            return node.over_expr
        if node.over_identifier is None:
            return None
        select = self._last_select()
        if select is None or select.window_exprs is None:
            return None
        return select.window_exprs.get(node.over_identifier)

    def _visit_json_call(self, node: ast.Call) -> str | None:
        function_name = node.name.lower()
        result_types = {
            "jsonextractstring": "VARCHAR",
            "jsonextractint": "BIGINT",
            "jsonextractuint": "DECIMAL(20, 0)",
            "jsonextractfloat": "DOUBLE",
            "jsonextractbool": "BOOLEAN",
        }
        if function_name not in {
            *result_types,
            "jsonextractraw",
            "jsonextractarrayraw",
            "jsonextract",
            "jsonhas",
            "jsonextractkeys",
            "jsonextractkeysandvalues",
            "jsonextractkeysandvaluesraw",
        }:
            return None
        if not node.args:
            raise QueryError(f"{node.name} expects at least one argument in the Trino dialect")

        source = self.visit(node.args[0])
        path_args = node.args[1:]
        if function_name == "jsonhas":
            if len(path_args) != 1:
                raise QueryError("JSONHas expects a single path component in the Trino dialect")
            path = self._json_path(path_args)
            self.context.add_value(path)
            return f"(json_extract({source}, ?) IS NOT NULL)"
        if function_name == "jsonextractkeys":
            path = self._json_path(path_args)
            self.context.add_value(path)
            return f"map_keys(CAST(json_extract({source}, ?) AS MAP(VARCHAR, JSON)))"
        if function_name in {"jsonextractkeysandvalues", "jsonextractkeysandvaluesraw"}:
            target_types = {
                "bool": "BOOLEAN",
                "float64": "DOUBLE",
                "int64": "BIGINT",
                "string": "VARCHAR",
                "uint64": "DECIMAL(20, 0)",
            }
            if function_name == "jsonextractkeysandvalues":
                if not path_args or not isinstance(path_args[-1], ast.Constant):
                    raise QueryError("JSONExtractKeysAndValues requires a literal target type in the Trino dialect")
                target_type = target_types.get(str(path_args[-1].value).lower())
                if target_type is None:
                    raise QueryError(
                        f"JSONExtractKeysAndValues target type '{path_args[-1].value}' is not supported in the Trino dialect"
                    )
                path_args = path_args[:-1]
            else:
                target_type = "JSON"
            path = self._json_path(path_args)
            self.context.add_value(path)
            return f"map_entries(CAST(json_extract({source}, ?) AS MAP(VARCHAR, {target_type})))"
        if function_name == "jsonextract":
            if len(path_args) != 1 or not isinstance(path_args[0], ast.Constant):
                raise QueryError("JSONExtract requires a literal target type in the Trino dialect")
            target_type = str(path_args[0].value).lower()
            if target_type == "array(string)":
                return f"CAST(json_extract({source}, '$') AS ARRAY(VARCHAR))"
            if target_type == "map(string, float64)":
                return f"CAST(json_extract({source}, '$') AS MAP(VARCHAR, DOUBLE))"
            raise QueryError(f"JSONExtract target type '{path_args[0].value}' is not supported in the Trino dialect")

        path = self._json_path(path_args)
        self.context.add_value(path)
        extracted = f"json_extract({source}, ?)"
        if function_name in {"jsonextractraw", "jsonextractarrayraw"}:
            return extracted
        scalar = f"json_extract_scalar({source}, ?)"
        if function_name == "jsonextractstring":
            return scalar
        return f"CAST({scalar} AS {result_types[function_name]})"

    def _json_path(self, path_args: Iterable[ast.Expr]) -> str:
        path = "$"
        for arg in path_args:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str | int):
                raise QueryError("Trino JSON paths require literal string or integer components")
            if isinstance(arg.value, int):
                path += f"[{arg.value}]"
            else:
                path += f".{json.dumps(arg.value, ensure_ascii=False)}"
        return path

    def _json_property_args(self, chain: Iterable[Any]) -> list[str]:
        path = "$" + "".join(f".{json.dumps(str(key), ensure_ascii=False)}" for key in chain)
        self.context.add_value(path)
        return ["?"]

    def _unsafe_json_extract_trim_quotes(self, unsafe_field: str, unsafe_args: list[str]) -> str:
        if not unsafe_args:
            return unsafe_field
        return f"json_extract_scalar({unsafe_field}, {unsafe_args[0]})"

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.ILike:
            return f"(lower({left}) LIKE lower({right}))"
        if op == ast.CompareOperationOp.NotILike:
            return f"(lower({left}) NOT LIKE lower({right}))"
        if op == ast.CompareOperationOp.Regex:
            return f"regexp_like({left}, {right})"
        if op == ast.CompareOperationOp.NotRegex:
            return f"NOT regexp_like({left}, {right})"
        if op == ast.CompareOperationOp.IRegex:
            return f"regexp_like({left}, concat('(?i)', {right}))"
        if op == ast.CompareOperationOp.NotIRegex:
            return f"NOT regexp_like({left}, concat('(?i)', {right}))"
        return super()._get_compare_op(op, left, right)

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        if unit == "week":
            if week_mode in {1, 3}:
                return f"date_trunc('week', {arg})"
            if week_mode == 0:
                return f"date_add('day', -1, date_trunc('week', date_add('day', 1, {arg})))"
            raise QueryError(f"Unsupported toStartOfWeek mode `{week_mode}` in Trino mode.")
        if unit == "isoyear":
            return f"date_trunc('week', date_parse(concat(CAST(year_of_week({arg}) AS VARCHAR), '-01-04'), '%Y-%m-%d'))"
        return f"date_trunc('{unit}', {arg})"

    def _render_minute_bucket(self, arg: str, bucket_size: int) -> str:
        bucket_seconds = bucket_size * 60
        return f"from_unixtime(floor(to_unixtime({arg}) / {bucket_seconds}) * {bucket_seconds})"

    def visit_cte(self, node: ast.CTE) -> str:
        if node.materialized is not None:
            raise QueryError("CTE materialization hints are not supported in the Trino dialect")
        if node.using_key is not None:
            raise QueryError("CTE USING KEY is not supported in the Trino dialect")
        if node.cte_type == "subquery":
            columns = (
                ""
                if node.columns is None
                else f"({', '.join(self._print_identifier(column) for column in node.columns)})"
            )
            return f"{self._print_identifier(node.name)}{columns} AS {self.visit(node.expr)}"
        raise QueryError("Scalar CTEs are not supported in the Trino dialect")

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> str:
        raise QueryError("UNPIVOT is not supported in the Trino dialect")

    def visit_pivot_expr(self, node: ast.PivotExpr) -> str:
        raise QueryError("PIVOT is not supported in the Trino dialect")
