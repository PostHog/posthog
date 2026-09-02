import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, ClassVar, NoReturn

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_locator import resolve_trino_table_locator
from posthog.hogql.database.trino_unnest_table import TrinoUnnestTable
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.printer.types import JoinExprResponse
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.database.models import Table

_TRINO_SIMPLE_TYPES = {
    "bigint": "BIGINT",
    "bool": "BOOLEAN",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "double": "DOUBLE",
    "double precision": "DOUBLE",
    "float": "DOUBLE",
    "float32": "REAL",
    "float64": "DOUBLE",
    "int": "BIGINT",
    "int8": "TINYINT",
    "int16": "SMALLINT",
    "int32": "INTEGER",
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
    r"^(decimal|numeric|varchar|char|fixedstring|datetime64|timestamp)\s*\((\d+(?:\s*,\s*\d+)?)\)$",
    re.IGNORECASE,
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
_TRINO_SET_OPERATORS = frozenset(
    {
        "UNION DISTINCT",
        "UNION ALL",
        "INTERSECT DISTINCT",
        "INTERSECT ALL",
        "INTERSECT",
        "EXCEPT DISTINCT",
        "EXCEPT ALL",
        "EXCEPT",
    }
)
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
_TRINO_WINDOW_FUNCTION_RENAMES = {
    "any": "arbitrary",
    "anylast": "arbitrary",
    "argmax": "max_by",
    "argmin": "min_by",
    "grouparray": "array_agg",
}
_TRINO_CONDITIONAL_WINDOW_FUNCTIONS = {
    "anyif": "arbitrary",
    "avgif": "avg",
    "countif": "count",
    "grouparrayif": "array_agg",
    "maxif": "max",
    "minif": "min",
    "sumif": "sum",
}
_TRINO_NO_FRAME_WINDOW_FUNCTIONS = frozenset(
    {"cume_dist", "dense_rank", "lag", "lead", "ntile", "percent_rank", "rank", "row_number"}
)
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
_TRINO_DATE_PARSE_SPECIFIERS = frozenset(
    {"%%", "%Y", "%y", "%m", "%c", "%d", "%e", "%H", "%k", "%h", "%I", "%l", "%i", "%s", "%S", "%f", "%p", "%T", "%r"}
)


@frozen
class _BinaryArguments:
    left: str
    right: str


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

    def _render_group_by_all_clause(self) -> str:
        return "GROUP BY AUTO"

    def _assert_set_operator_supported(self, set_operator: str) -> None:
        if set_operator not in _TRINO_SET_OPERATORS:
            self._unsupported(
                "TRINO_SET_OPERATOR_UNSUPPORTED",
                f"Set operator '{set_operator}' is not supported in Trino mode.",
            )

    @staticmethod
    def _validate_row_count(value: ast.Expr, clause: str) -> int:
        if (
            not isinstance(value, ast.Constant)
            or isinstance(value.value, bool)
            or not isinstance(value.value, int)
            or value.value < 0
        ):
            raise TrinoLoweringError(
                "TRINO_ROW_COUNT_NON_LITERAL",
                clause,
                value,
                detail=f"{clause} must be a non-negative integer literal in Trino mode.",
            )
        return value.value

    def _append_select_limit_and_offset(
        self, clauses: list[str | None], node: ast.SelectQuery, limit: ast.Expr | None
    ) -> None:
        if node.offset is not None:
            clauses.append(f"OFFSET {self._validate_row_count(node.offset, 'OFFSET')} ROWS")
        if limit is None:
            return
        count = self._validate_row_count(limit, "LIMIT")
        if node.limit_percent:
            self._unsupported("TRINO_LIMIT_PERCENT_UNSUPPORTED", "LIMIT PERCENT is not supported in Trino mode.")
        if node.limit_with_ties:
            if not node.order_by:
                self._unsupported(
                    "TRINO_WITH_TIES_ORDER_REQUIRED",
                    "LIMIT WITH TIES requires ORDER BY in Trino mode.",
                    node,
                )
            clauses.append(f"FETCH FIRST {count} ROWS WITH TIES")
        else:
            clauses.append(f"LIMIT {count}")

    def _append_set_limit_and_offset(self, sql: str, node: ast.SelectSetQuery) -> str:
        suffixes: list[str] = []
        if node.offset is not None:
            suffixes.append(f"OFFSET {self._validate_row_count(node.offset, 'OFFSET')} ROWS")
        if node.limit is not None:
            count = self._validate_row_count(node.limit, "LIMIT")
            if node.limit_percent:
                self._unsupported("TRINO_LIMIT_PERCENT_UNSUPPORTED", "LIMIT PERCENT is not supported in Trino mode.")
            if node.limit_with_ties:
                self._unsupported(
                    "TRINO_SET_WITH_TIES_UNSUPPORTED",
                    "WITH TIES is not supported on Trino set queries.",
                    node,
                )
            suffixes.append(f"LIMIT {count}")
        if not suffixes:
            return sql
        separator = f"\n{self.indent(1)}" if self.pretty else " "
        return sql.rstrip() + separator + separator.join(suffixes)

    def _unsupported(self, feature_code: str, detail: str, node: ast.Expr | None = None) -> NoReturn:
        construct = node.name if isinstance(node, ast.Call) else node.__class__.__name__ if node else detail
        raise TrinoLoweringError(feature_code, construct, node, detail=detail)

    def _invalid_function_arguments(self, node: ast.Call, detail: str) -> NoReturn:
        self._unsupported("TRINO_FUNCTION_ARGUMENTS_UNSUPPORTED", detail, node)

    def visit_call(self, node: ast.Call) -> str:
        name = node.name.lower()
        if find_hogql_aggregation(node.name) is None and (
            node.distinct or node.within_group is not None or node.order_by is not None or node.filter_expr is not None
        ):
            self._unsupported(
                "TRINO_SCALAR_FUNCTION_MODIFIER_UNSUPPORTED",
                f"Scalar function '{node.name}' does not accept aggregate modifiers in Trino mode.",
                node,
            )
        if name in {"empty", "notempty"}:
            return self._visit_empty(node, negated=name == "notempty")
        if name in {"in", "notin"}:
            binary_args = self._visit_binary_args(node)
            return f"({binary_args.left} {'NOT IN' if name == 'notin' else 'IN'} {binary_args.right})"
        if name == "mapfromarrays":
            return self._visit_map_from_arrays(node)
        if name == "length" and node.args and isinstance(self._resolve_type(node.args[0]), ast.ArrayType):
            return self._visit_unary_function(node, "cardinality")
        if name in {"toint", "tointorzero", "tointordefault"} and node.args:
            arg = node.args[0]
            arg_type = arg.type.resolve_constant_type(self.context) if arg.type is not None else None
            rendered = self.visit(arg)
            if isinstance(arg_type, ast.DateType):
                return f"date_diff('day', DATE '1970-01-01', {rendered})"
            if isinstance(arg_type, ast.DateTimeType):
                return f"CAST(to_unixtime({rendered}) AS BIGINT)"
            if isinstance(arg_type, ast.BooleanType):
                return f"CASE WHEN {rendered} THEN 1 ELSE 0 END"
        if name == "todatetime" and node.args:
            value_expr = node.args[0]
            if (
                isinstance(value_expr, ast.Constant)
                and isinstance(value_expr.value, str)
                and re.search(r"T.*(?:Z|[+-]\d\d:\d\d)$", value_expr.value)
            ):
                timestamp = f"from_iso8601_timestamp({self.visit(value_expr)})"
                if len(node.args) == 1:
                    return f"CAST({timestamp} AS TIMESTAMP)"
                if len(node.args) == 2:
                    return f"at_timezone({timestamp}, {self.visit(node.args[1])})"
                self._invalid_function_arguments(
                    node, "toDateTime expects a value and optional timezone in Trino mode."
                )
            if len(node.args) == 2:
                return f"with_timezone(CAST({self.visit(value_expr)} AS TIMESTAMP), {self.visit(node.args[1])})"
        if name == "totimezone":
            binary_args = self._visit_binary_args(node)
            return f"at_timezone(with_timezone(CAST({binary_args.left} AS TIMESTAMP), 'UTC'), {binary_args.right})"
        if name == "parsedatetime":
            return self._visit_parse_datetime(node)
        if name == "tolastdayofweek":
            return self._visit_to_last_day_of_week(node)
        if name == "todatetime64":
            return self._visit_to_datetime64(node)
        if name == "concat":
            if node.distinct or node.order_by:
                self._unsupported(
                    "TRINO_CONCAT_MODIFIER_UNSUPPORTED",
                    "concat does not support DISTINCT or ORDER BY in Trino mode.",
                    node,
                )
            rendered = [f"CAST({self.visit(arg)} AS VARCHAR)" for arg in node.args]
            return f"concat({', '.join(rendered)})"
        if name == "repeat":
            binary_args = self._visit_binary_args(node)
            return (
                f"CASE WHEN {binary_args.left} IS NULL OR {binary_args.right} IS NULL THEN NULL "
                f"ELSE array_join(repeat({binary_args.left}, {binary_args.right}), '') END"
            )
        if name == "sum" and len(node.args) == 1 and self._is_dynamic_property(node.args[0]):
            lowered = clone_expr(node)
            lowered.args = [ast.Call(name="toFloat", args=[lowered.args[0]])]
            return super().visit_call(lowered)
        if name in {
            "jsonextract",
            "jsonextractstring",
            "jsonextractraw",
            "jsonextractarrayraw",
            "jsonextractint",
            "jsonextractuint",
            "jsonextractfloat",
            "jsonextractbool",
        }:
            return self._visit_json_extract(node)
        if name in {"jsonextractkeys", "jsonextractkeysandvaluesraw", "jsonhas", "jsonlength"}:
            return self._visit_json_metadata(node)
        if name == "jsonextractkeysandvalues":
            return self._visit_json_metadata(node)
        if name == "tojsonstring":
            return self._visit_to_json_string(node)
        if name == "arraymap":
            return self._visit_lambda_array_call(node, "transform")
        if name == "arrayfilter":
            return self._visit_lambda_array_call(node, "filter")
        if name == "arrayelement":
            return self._visit_binary_function(node, "element_at")
        if name == "arraydistinct":
            return self._visit_unary_function(node, "array_distinct")
        if name == "extractall":
            if len(node.args) != 2:
                self._invalid_function_arguments(node, "extractAll expects exactly 2 arguments in Trino mode.")
            return f"regexp_extract_all({self.visit(node.args[0])}, {self.visit(node.args[1])}, 1)"
        if name == "arraysort":
            return self._visit_unary_function(node, "array_sort")
        if name == "arrayflatten":
            return self._visit_unary_function(node, "flatten")
        if name == "arraymin":
            return self._visit_unary_function(node, "array_min")
        if name == "arrayfirst":
            return self._visit_array_first(node)
        if name == "arrayconcat":
            return self._visit_variadic_function(node, "concat", minimum=2)
        if name == "arraysum":
            return self._visit_unary_function(node, "array_sum")
        if name == "has":
            return self._visit_binary_function(node, "contains")
        if name == "hasany":
            binary_args = self._visit_binary_args(node)
            return f"(cardinality(array_intersect({binary_args.left}, {binary_args.right})) > 0)"
        if name == "hasall":
            binary_args = self._visit_binary_args(node)
            return f"(cardinality(array_except({binary_args.right}, {binary_args.left})) = 0)"
        if name == "range":
            return self._visit_range(node)
        if name in {"argmax", "argmin"}:
            return self._visit_binary_function(node, "max_by" if name == "argmax" else "min_by")
        if name in {"argmaxif", "argminif"}:
            if len(node.args) != 3:
                self._invalid_function_arguments(node, f"{node.name} expects exactly 3 arguments in Trino mode.")
            values = [self.visit(arg) for arg in node.args]
            target = "max_by" if name == "argmaxif" else "min_by"
            return f"{target}({values[0]}, {values[1]}) FILTER (WHERE {values[2]})"
        if name == "groupuniqarray":
            if len(node.args) != 1:
                self._invalid_function_arguments(node, "groupUniqArray expects exactly 1 argument in Trino mode.")
            return f"array_agg(DISTINCT {self.visit(node.args[0])})"
        if name == "grouparrayif":
            if len(node.args) != 2:
                self._invalid_function_arguments(node, "groupArrayIf expects exactly 2 arguments in Trino mode.")
            return f"array_agg({self.visit(node.args[0])}) FILTER (WHERE {self.visit(node.args[1])})"
        if name == "groupuniqarrayif":
            if len(node.args) != 2:
                self._invalid_function_arguments(node, "groupUniqArrayIf expects exactly 2 arguments in Trino mode.")
            return f"array_agg(DISTINCT {self.visit(node.args[0])}) FILTER (WHERE {self.visit(node.args[1])})"
        if name == "countdistinct":
            return self._visit_count_distinct(node)
        if name == "todecimal":
            return self._visit_to_decimal(node)
        if name == "tuple":
            return f"ROW({', '.join(self.visit(arg) for arg in node.args)})"
        if name == "tupleelement":
            return self._visit_tuple_element(node)
        if name == "match":
            return self._visit_binary_function(node, "regexp_like")
        if name in {"splitbychar", "splitbystring"}:
            binary_args = self._visit_binary_args(node)
            return f"split({binary_args.right}, {binary_args.left})"
        if name == "md5":
            rendered_value = self._visit_unary_arg(node)
            return f"to_hex(md5(to_utf8(CAST({rendered_value} AS VARCHAR))))"
        if name == "extract":
            return self._visit_extract(node)
        if name in {"quantile", "quantileif"}:
            return self._visit_quantile(node, filtered=name == "quantileif")
        if name in {"dateadd", "datesub"}:
            if len(node.args) == 2:
                binary_args = self._visit_binary_args(node)
                return f"({binary_args.left} {'+' if name == 'dateadd' else '-'} {binary_args.right})"
            if len(node.args) == 3:
                unit, amount, value = (self.visit(arg) for arg in node.args)
                if name == "datesub":
                    amount = f"-({amount})"
                return f"date_add({unit}, {amount}, {value})"
            self._invalid_function_arguments(node, f"{node.name} expects two or three arguments in Trino mode.")
        if name in {"datetrunc", "date_trunc"} and len(node.args) == 3:
            unit, value, timezone = (self.visit(arg) for arg in node.args)
            zoned_value = f"at_timezone(with_timezone(CAST({value} AS TIMESTAMP), 'UTC'), {timezone})"
            return f"date_trunc({unit}, {zoned_value})"
        if name == "date_part":
            return self._visit_date_part(node)
        if name == "json_value":
            return self._visit_json_value(node)
        return super().visit_call(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> JoinExprResponse:
        if node.join_type is not None and node.join_type not in _TRINO_JOIN_TYPES:
            self._unsupported(
                "TRINO_JOIN_TYPE_UNSUPPORTED",
                f"Join type '{node.join_type}' is not supported in Trino mode.",
                node,
            )
        if node.constraint is not None and node.join_type in {None, "CROSS JOIN"}:
            self._unsupported(
                "TRINO_JOIN_CONSTRAINT_UNSUPPORTED",
                f"{node.join_type or 'FROM'} does not accept a join constraint in Trino mode.",
                node,
            )
        return super().visit_join_expr(node)

    def visit_named_argument(self, node: ast.NamedArgument) -> NoReturn:
        self._unsupported(
            "TRINO_NAMED_ARGUMENT_UNSUPPORTED",
            "Named arguments are not supported in Trino mode.",
            node,
        )

    def visit_order_expr(self, node: ast.OrderExpr) -> str:
        if node.with_fill is not None:
            self._unsupported("TRINO_WITH_FILL_UNSUPPORTED", "WITH FILL is not supported in Trino mode.", node)
        return super().visit_order_expr(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> str:
        left_type = self._resolve_type(node.left)
        right_type = self._resolve_type(node.right)
        left_cast: str | None = None
        right_cast: str | None = None

        if isinstance(left_type, ast.DateTimeType) and isinstance(right_type, ast.StringType):
            right_cast = "TIMESTAMP"
        elif isinstance(right_type, ast.DateTimeType) and isinstance(left_type, ast.StringType):
            left_cast = "TIMESTAMP"
        elif isinstance(left_type, ast.DateType) and isinstance(right_type, ast.StringType):
            right_cast = "DATE"
        elif isinstance(right_type, ast.DateType) and isinstance(left_type, ast.StringType):
            left_cast = "DATE"
        elif self._is_dynamic_property(node.left) and isinstance(right_type, ast.BooleanType):
            left_cast = "BOOLEAN"
        elif self._is_dynamic_property(node.right) and isinstance(left_type, ast.BooleanType):
            right_cast = "BOOLEAN"
        else:
            return super().visit_compare_operation(node)

        left = self.visit(node.left)
        right = self.visit(node.right)
        if left_cast is not None:
            left = f"CAST({left} AS {left_cast})"
        if right_cast is not None:
            right = f"CAST({right} AS {right_cast})"
        return self._get_compare_op(node.op, left, right)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> str:
        left = self.visit(node.left)
        right = self.visit(node.right)
        if node.op == ast.ArithmeticOperationOp.Div:
            return f"(CAST({left} AS DOUBLE) / CAST({right} AS DOUBLE))"
        lowered = False
        if self._is_dynamic_property(node.left) and self._is_numeric(node.right):
            left = f"CAST({left} AS DOUBLE)"
            lowered = True
        if self._is_dynamic_property(node.right) and self._is_numeric(node.left):
            right = f"CAST({right} AS DOUBLE)"
            lowered = True
        operators = {
            ast.ArithmeticOperationOp.Add: "+",
            ast.ArithmeticOperationOp.Sub: "-",
            ast.ArithmeticOperationOp.Mult: "*",
            ast.ArithmeticOperationOp.Mod: "%",
        }
        operator = operators.get(node.op)
        if operator is not None and lowered:
            return f"({left} {operator} {right})"
        return super().visit_arithmetic_operation(node)

    def _resolve_type(self, node: ast.Expr) -> ast.ConstantType | None:
        return node.type.resolve_constant_type(self.context) if node.type is not None else None

    def _is_dynamic_property(self, node: ast.Expr) -> bool:
        while isinstance(node, ast.Alias):
            node = node.expr
        return isinstance(node, ast.PropertyAccess)

    def _is_numeric(self, node: ast.Expr) -> bool:
        return isinstance(self._resolve_type(node), (ast.IntegerType, ast.FloatType, ast.DecimalType))

    def _visit_json_extract(self, node: ast.Call) -> str:
        name = node.name.lower()
        if name == "jsonextractarrayraw" and len(node.args) == 1:
            source = self.visit(node.args[0])
            value = self._print_identifier("__hogql_json_value")
            return (
                f"transform(CAST(json_parse(CAST({source} AS VARCHAR)) AS ARRAY(JSON)), "
                f"{value} -> json_format({value}))"
            )
        if len(node.args) < 2:
            self._invalid_function_arguments(node, f"{node.name} expects a JSON expression and key path in Trino mode.")
        if name == "jsonextract":
            return self._visit_typed_json_extract(node)
        path_members: list[str | int] = []
        for key in node.args[1:]:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, (str, int)):
                self._unsupported(
                    "TRINO_JSON_DYNAMIC_PATH_UNSUPPORTED",
                    f"{node.name} requires a constant key path in Trino mode.",
                    node,
                )
            path_members.append(key.value)
        path = self._json_path(path_members)
        source = self.visit(node.args[0])
        extracted = f"json_extract({source}, {path})"
        if name in {"jsonextractraw", "jsonextractarrayraw"}:
            return f"json_format({extracted})"
        scalar = f"json_extract_scalar({source}, {path})"
        casts = {
            "jsonextractint": "BIGINT",
            "jsonextractuint": "DECIMAL(20, 0)",
            "jsonextractfloat": "DOUBLE",
            "jsonextractbool": "BOOLEAN",
        }
        target_type = casts.get(name)
        return scalar if target_type is None else f"CAST({scalar} AS {target_type})"

    def _visit_typed_json_extract(self, node: ast.Call) -> str:
        type_arg = node.args[-1]
        if not isinstance(type_arg, ast.Constant) or not isinstance(type_arg.value, str):
            self._unsupported(
                "TRINO_JSON_DYNAMIC_TARGET_TYPE_UNSUPPORTED",
                "JSONExtract requires a constant target type in Trino mode.",
                node,
            )
        target = self._trino_json_type(type_arg.value, node)
        path_members: list[str | int] = []
        for key in node.args[1:-1]:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, (str, int)):
                self._unsupported(
                    "TRINO_JSON_DYNAMIC_PATH_UNSUPPORTED",
                    "JSONExtract requires a constant key path in Trino mode.",
                    node,
                )
            path_members.append(key.value)
        source = self.visit(node.args[0])
        path = self._json_path(path_members)
        extractor = "json_extract" if target.startswith(("ARRAY", "MAP")) else "json_extract_scalar"
        return f"CAST({extractor}({source}, {path}) AS {target})"

    def _trino_json_type(self, type_name: str, node: ast.Call) -> str:
        normalized = " ".join(type_name.strip().lower().split())
        scalar_types = {
            "bool": "BOOLEAN",
            "float32": "REAL",
            "float64": "DOUBLE",
            "int8": "TINYINT",
            "int16": "SMALLINT",
            "int32": "INTEGER",
            "int64": "BIGINT",
            "string": "VARCHAR",
            "uint8": "SMALLINT",
            "uint16": "INTEGER",
            "uint32": "BIGINT",
            "uint64": "DECIMAL(20, 0)",
        }
        target = scalar_types.get(normalized)
        if target is not None:
            return target
        if normalized.startswith("nullable(") and normalized.endswith(")"):
            return self._trino_json_type(normalized[9:-1], node)
        if normalized.startswith("array(") and normalized.endswith(")"):
            return f"ARRAY({self._trino_json_type(normalized[6:-1], node)})"
        if normalized.startswith("map(") and normalized.endswith(")"):
            arguments = self._split_type_arguments(normalized[4:-1])
            if len(arguments) == 2 and arguments[0] == "string":
                return f"MAP(VARCHAR, {self._trino_json_type(arguments[1], node)})"
        self._unsupported(
            "TRINO_JSON_TARGET_TYPE_UNSUPPORTED",
            f"JSONExtract target type '{type_name}' is not supported in Trino mode.",
            node,
        )

    def _visit_json_metadata(self, node: ast.Call) -> str:
        name = node.name.lower()
        if name == "jsonextractkeysandvaluesraw":
            if len(node.args) != 1:
                self._invalid_function_arguments(
                    node, "JSONExtractKeysAndValuesRaw expects exactly 1 argument in Trino mode."
                )
            source = self.visit(node.args[0])
            entry = self._print_identifier("__hogql_json_entry")
            return (
                f"transform(map_entries(CAST(json_parse(CAST({source} AS VARCHAR)) AS MAP(VARCHAR, JSON))), "
                f"{entry} -> ROW({entry}[1], json_format({entry}[2])))"
            )
        if not node.args:
            self._invalid_function_arguments(node, f"{node.name} expects a JSON expression in Trino mode.")
        source = self.visit(node.args[0])
        path_args = node.args[1:]
        target_type: str | None = None
        if name == "jsonextractkeysandvalues":
            if not path_args or not isinstance(path_args[-1], ast.Constant) or not isinstance(path_args[-1].value, str):
                self._invalid_function_arguments(
                    node, "JSONExtractKeysAndValues requires a constant target type in Trino mode."
                )
            target_types = {
                "bool": "BOOLEAN",
                "float64": "DOUBLE",
                "int64": "BIGINT",
                "string": "VARCHAR",
                "uint64": "DECIMAL(20, 0)",
            }
            target_type = target_types.get(path_args[-1].value.lower())
            if target_type is None:
                self._unsupported(
                    "TRINO_JSON_TARGET_TYPE_UNSUPPORTED",
                    f"JSONExtractKeysAndValues target type '{path_args[-1].value}' is not supported in Trino mode.",
                    node,
                )
            path_args = path_args[:-1]
        path_members: list[str | int] = []
        for key in path_args:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, (str, int)):
                self._unsupported(
                    "TRINO_JSON_DYNAMIC_PATH_UNSUPPORTED",
                    f"{node.name} requires a constant key path in Trino mode.",
                    node,
                )
            path_members.append(key.value)
        path = self._json_path(path_members)
        if name == "jsonhas":
            return f"(json_extract({source}, {path}) IS NOT NULL)"
        if name == "jsonlength":
            return f"json_size({source}, {path})"
        if name == "jsonextractkeysandvalues":
            return f"map_entries(CAST(json_extract({source}, {path}) AS MAP(VARCHAR, {target_type})))"
        return f"map_keys(CAST(json_extract({source}, {path}) AS MAP(VARCHAR, JSON)))"

    def _visit_to_datetime64(self, node: ast.Call) -> str:
        if len(node.args) not in {1, 2}:
            self._invalid_function_arguments(node, "toDateTime64 expects a value and optional precision in Trino mode.")
        precision = 3
        if len(node.args) == 2:
            precision_arg = node.args[1]
            if (
                not isinstance(precision_arg, ast.Constant)
                or isinstance(precision_arg.value, bool)
                or not isinstance(precision_arg.value, int)
                or not 0 <= precision_arg.value <= 12
            ):
                self._unsupported(
                    "TRINO_DATETIME_PRECISION_UNSUPPORTED",
                    "toDateTime64 requires an integer precision from 0 to 12 in Trino mode.",
                    node,
                )
            precision = precision_arg.value
        return f"CAST({self.visit(node.args[0])} AS TIMESTAMP({precision}))"

    def _visit_parse_datetime(self, node: ast.Call) -> str:
        if len(node.args) not in {2, 3}:
            self._invalid_function_arguments(
                node, "parseDateTime expects a value, format, and optional timezone in Trino mode."
            )
        format_arg = node.args[1]
        if not isinstance(format_arg, ast.Constant) or not isinstance(format_arg.value, str):
            self._unsupported(
                "TRINO_DATETIME_FORMAT_NON_CONSTANT",
                "parseDateTime requires a constant format in Trino mode.",
                node,
            )
        directives = re.findall(r"%.", format_arg.value)
        if any(directive not in _TRINO_DATE_PARSE_SPECIFIERS for directive in directives):
            self._unsupported(
                "TRINO_DATETIME_FORMAT_UNSUPPORTED",
                "parseDateTime uses a format directive that does not have matching Trino semantics.",
                node,
            )
        parsed = f"TRY(date_parse({self.visit(node.args[0])}, {self.visit(format_arg)}))"
        if len(node.args) == 3:
            return f"with_timezone({parsed}, {self.visit(node.args[2])})"
        return parsed

    def _visit_to_last_day_of_week(self, node: ast.Call) -> str:
        if len(node.args) not in {1, 2}:
            self._invalid_function_arguments(node, "toLastDayOfWeek expects a value and optional mode in Trino mode.")
        mode = 0
        if len(node.args) == 2:
            mode_arg = node.args[1]
            if (
                not isinstance(mode_arg, ast.Constant)
                or isinstance(mode_arg.value, bool)
                or not isinstance(mode_arg.value, int)
                or not 0 <= mode_arg.value <= 9
            ):
                self._unsupported(
                    "TRINO_WEEK_MODE_UNSUPPORTED",
                    "toLastDayOfWeek requires a constant ClickHouse week mode from 0 to 9 in Trino mode.",
                    node,
                )
            mode = mode_arg.value
        day_offset = 5 if mode % 2 == 0 else 6
        value = self.visit(node.args[0])
        return f"CAST(date_add('day', {day_offset}, date_trunc('week', {value})) AS DATE)"

    def _visit_date_part(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "date_part expects a unit and value in Trino mode.")
        unit = node.args[0]
        if (
            not isinstance(unit, ast.Constant)
            or not isinstance(unit.value, str)
            or unit.value.lower() not in _TRINO_EXTRACT_FIELDS
        ):
            self._unsupported(
                "TRINO_DATE_PART_UNIT_UNSUPPORTED",
                "date_part requires a supported constant unit in Trino mode.",
                node,
            )
        return f"EXTRACT({unit.value.upper()} FROM {self.visit(node.args[1])})"

    def _visit_to_json_string(self, node: ast.Call) -> str:
        value = self._visit_unary_arg(node)
        return f"json_format(CAST({value} AS JSON))"

    def _visit_empty(self, node: ast.Call, *, negated: bool) -> str:
        if len(node.args) != 1:
            self._invalid_function_arguments(node, f"{node.name} expects exactly 1 argument in Trino mode.")
        arg = node.args[0]
        rendered = self.visit(arg)
        value_expr = arg
        while isinstance(value_expr, ast.Alias):
            value_expr = value_expr.expr
        arg_type = self._resolve_type(value_expr)
        if isinstance(value_expr, ast.PropertyAccess):
            arg_type = ast.StringType(nullable=True)
        conjunction = "AND" if negated else "OR"
        if isinstance(arg_type, (ast.ArrayType, ast.MapType)):
            comparison = "> 0" if negated else "= 0"
            return f"({rendered} IS {'NOT ' if negated else ''}NULL {conjunction} cardinality({rendered}) {comparison})"
        if isinstance(arg_type, ast.StringType):
            comparison = "<> ''" if negated else "= ''"
            return f"({rendered} IS {'NOT ' if negated else ''}NULL {conjunction} {rendered} {comparison})"
        self._unsupported(
            "TRINO_EMPTY_ARGUMENT_TYPE_UNSUPPORTED",
            f"{node.name} requires a string, array, or map argument in Trino mode.",
            node,
        )

    def _json_path(self, members: Iterable[str | int]) -> str:
        path = "$"
        for member in members:
            if isinstance(member, int):
                path += f"[{member}]"
            else:
                escaped = str(member).replace("\\", "\\\\").replace('"', '\\"')
                path += f'["{escaped}"]'
        return self.context.add_value(path)

    def _visit_lambda_array_call(self, node: ast.Call, target: str) -> str:
        if len(node.args) != 2 or not isinstance(node.args[0], ast.Lambda):
            self._invalid_function_arguments(node, f"{node.name} expects a lambda and array in Trino mode.")
        return f"{target}({self.visit(node.args[1])}, {self.visit(node.args[0])})"

    def _visit_unary_function(self, node: ast.Call, target: str) -> str:
        return f"{target}({self._visit_unary_arg(node)})"

    def _visit_unary_arg(self, node: ast.Call) -> str:
        if len(node.args) != 1:
            self._invalid_function_arguments(node, f"{node.name} expects exactly 1 argument in Trino mode.")
        return self.visit(node.args[0])

    def _visit_binary_args(self, node: ast.Call) -> _BinaryArguments:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, f"{node.name} expects exactly 2 arguments in Trino mode.")
        return _BinaryArguments(left=self.visit(node.args[0]), right=self.visit(node.args[1]))

    def _visit_binary_function(self, node: ast.Call, target: str) -> str:
        binary_args = self._visit_binary_args(node)
        return f"{target}({binary_args.left}, {binary_args.right})"

    def _visit_variadic_function(self, node: ast.Call, target: str, minimum: int) -> str:
        if len(node.args) < minimum:
            self._invalid_function_arguments(node, f"{node.name} expects at least {minimum} arguments in Trino mode.")
        return f"{target}({', '.join(self.visit(arg) for arg in node.args)})"

    def _visit_range(self, node: ast.Call) -> str:
        if len(node.args) == 1:
            start = "0"
            end = self.visit(node.args[0])
        elif len(node.args) == 2:
            start = self.visit(node.args[0])
            end = self.visit(node.args[1])
        else:
            self._invalid_function_arguments(node, "range expects one or two arguments in Trino mode.")
        value = self._print_identifier("__hogql_range_value")
        return f"filter(sequence({start}, greatest(({end}) - 1, {start})), {value} -> ({value} < {end}))"

    def _visit_map_from_arrays(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "mapFromArrays expects key and value arrays in Trino mode.")
        keys = node.args[0]
        if not isinstance(keys, ast.Array) or any(
            not isinstance(key, ast.Constant) or key.value is None for key in keys.exprs
        ):
            self._unsupported(
                "TRINO_MAP_KEYS_UNPROVEN",
                "mapFromArrays requires constant non-null keys so Trino map semantics can be verified.",
                node,
            )
        key_values = [key.value for key in keys.exprs if isinstance(key, ast.Constant)]
        if any(value in key_values[:index] for index, value in enumerate(key_values)):
            self._unsupported(
                "TRINO_MAP_DUPLICATE_KEYS_UNSUPPORTED",
                "ClickHouse maps with duplicate keys cannot be represented safely in Trino.",
                node,
            )
        return self._visit_binary_function(node, "map")

    def _visit_array_first(self, node: ast.Call) -> str:
        if len(node.args) != 2 or not isinstance(node.args[0], ast.Lambda):
            self._invalid_function_arguments(node, "arrayFirst expects a lambda and array in Trino mode.")
        filtered = f"element_at(filter({self.visit(node.args[1])}, {self.visit(node.args[0])}), 1)"
        array_type = node.args[1].type.resolve_constant_type(self.context) if node.args[1].type is not None else None
        if not isinstance(array_type, ast.ArrayType):
            self._unsupported(
                "TRINO_ARRAY_FIRST_TYPE_UNRESOLVED",
                "arrayFirst requires a resolved array type in Trino mode.",
                node,
            )
        defaults: list[tuple[type[ast.ConstantType], object]] = [
            (ast.IntegerType, 0),
            (ast.FloatType, 0.0),
            (ast.DecimalType, 0),
            (ast.StringType, ""),
            (ast.BooleanType, False),
        ]
        default = next((value for type_class, value in defaults if isinstance(array_type.item_type, type_class)), None)
        if default is None:
            self._unsupported(
                "TRINO_ARRAY_FIRST_ITEM_TYPE_UNSUPPORTED",
                "arrayFirst does not support this array item type in Trino mode.",
                node,
            )
        return f"coalesce({filtered}, {self.visit(ast.Constant(value=default))})"

    def _visit_count_distinct(self, node: ast.Call) -> str:
        if not node.args:
            self._invalid_function_arguments(node, "countDistinct expects at least one argument in Trino mode.")
        arguments = [self.visit(arg) for arg in node.args]
        value = arguments[0] if len(arguments) == 1 else f"ROW({', '.join(arguments)})"
        return f"count(DISTINCT {value})"

    def _visit_to_decimal(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "toDecimal expects a value and scale in Trino mode.")
        scale = node.args[1]
        if not isinstance(scale, ast.Constant) or isinstance(scale.value, bool) or not isinstance(scale.value, int):
            self._unsupported(
                "TRINO_DECIMAL_NON_CONSTANT_SCALE",
                "toDecimal requires a constant integer scale in Trino mode.",
                node,
            )
        if scale.value < 0 or scale.value > 38:
            self._unsupported(
                "TRINO_DECIMAL_SCALE_OUT_OF_RANGE",
                "toDecimal scale must be between 0 and 38 in Trino mode.",
                node,
            )
        return f"CAST({self.visit(node.args[0])} AS DECIMAL(38, {scale.value}))"

    def _visit_tuple_element(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "tupleElement expects a tuple and index in Trino mode.")
        index = node.args[1]
        if not isinstance(index, ast.Constant) or isinstance(index.value, bool) or not isinstance(index.value, int):
            self._unsupported(
                "TRINO_TUPLE_ELEMENT_NON_CONSTANT_INDEX",
                "tupleElement requires a constant integer index in Trino mode.",
                node,
            )
        if index.value < 1:
            self._unsupported(
                "TRINO_TUPLE_ELEMENT_INDEX_OUT_OF_RANGE",
                "tupleElement index must be positive in Trino mode.",
                node,
            )
        source = node.args[0]
        if isinstance(source, ast.Call) and source.name.lower() == "tuple":
            if index.value > len(source.args):
                self._unsupported(
                    "TRINO_TUPLE_ELEMENT_INDEX_OUT_OF_RANGE",
                    "tupleElement index is out of range in Trino mode.",
                    node,
                )
            return self.visit(source.args[index.value - 1])
        return f"({self.visit(source)})[{index.value}]"

    def _visit_extract(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "extract expects exactly 2 arguments in Trino mode.")
        pattern = node.args[1]
        if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
            self._unsupported(
                "TRINO_EXTRACT_DYNAMIC_PATTERN_UNSUPPORTED",
                "extract requires a constant regular expression in Trino mode.",
                node,
            )
        group = self._first_regex_capture_group(pattern.value)
        extracted = f"regexp_extract({self.visit(node.args[0])}, {self.visit(pattern)}, {group})"
        return f"coalesce({extracted}, {self.visit(ast.Constant(value=''))})"

    def _first_regex_capture_group(self, pattern: str) -> int:
        escaped = False
        in_character_class = False
        for index, character in enumerate(pattern):
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == "[":
                in_character_class = True
                continue
            if character == "]":
                in_character_class = False
                continue
            if character == "(" and not in_character_class and pattern[index + 1 : index + 2] != "?":
                return 1
        return 0

    def _visit_quantile(self, node: ast.Call, *, filtered: bool) -> str:
        expected_arguments = 2 if filtered else 1
        if len(node.args) != expected_arguments or node.params is None or len(node.params) != 1:
            self._invalid_function_arguments(node, f"{node.name} expects one percentile parameter in Trino mode.")
        aggregate = f"approx_percentile({self.visit(node.args[0])}, {self.visit(node.params[0])})"
        if filtered:
            aggregate += f" FILTER (WHERE {self.visit(node.args[1])})"
        return aggregate

    def _visit_json_value(self, node: ast.Call) -> str:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, "JSON_VALUE expects a JSON expression and path in Trino mode.")
        path = node.args[1]
        if not isinstance(path, ast.Constant) or not isinstance(path.value, str):
            self._unsupported(
                "TRINO_JSON_DYNAMIC_PATH_UNSUPPORTED",
                "JSON_VALUE requires a constant path in Trino mode.",
                node,
            )
        if "\0" in path.value:
            self._unsupported(
                "TRINO_JSON_PATH_INVALID",
                "JSON_VALUE path contains an invalid NUL character.",
                node,
            )
        path_value = path.value if path.value.lstrip().startswith(("lax ", "strict ")) else f"lax {path.value}"
        path_literal = "'" + path_value.replace("'", "''") + "'"
        return f"json_value({self.visit(node.args[0])}, {path_literal})"

    def _print_table_sql(self, table: "Table") -> str:
        return self._print_table(table)

    def _print_table(self, table: "Table") -> str:
        if isinstance(table, NumbersTable):
            return "UNNEST"
        if isinstance(table, TrinoUnnestTable):
            return table.to_printed_trino(self.context)
        locator = resolve_trino_table_locator(table, self.context)
        if locator is not None:
            return ".".join(escape_trino_identifier(part) for part in locator)
        self._unsupported(
            "TRINO_TABLE_LOCATOR_MISSING",
            f"Table '{table.name or table.__class__.__name__}' has no Trino physical locator.",
        )

    def visit_lambda(self, node: ast.Lambda) -> str:
        identifiers = [self._print_identifier(arg) for arg in node.args]
        if not identifiers:
            self._unsupported(
                "TRINO_LAMBDA_ARGUMENT_REQUIRED", "Lambdas require at least one argument in Trino mode.", node
            )
        arguments = identifiers[0] if len(identifiers) == 1 else f"({', '.join(identifiers)})"
        return f"{arguments} -> {self.visit(node.expr)}"

    def visit_array(self, node: ast.Array) -> str:
        return f"ARRAY[{', '.join(self.visit(expr) for expr in node.exprs)}]"

    def visit_tuple_access(self, node: ast.TupleAccess) -> str:
        source = self.visit(node.tuple)
        return f"({source})[{node.index}]"

    def visit_positional_ref(self, node: ast.PositionalRef) -> str:
        if not isinstance(node.index, int) or node.index < 1:
            self._unsupported(
                "TRINO_POSITIONAL_REFERENCE_INVALID",
                f"Positional reference must be a positive integer, got {node.index}.",
                node,
            )
        return str(node.index)

    def visit_window_function(self, node: ast.WindowFunction) -> str:
        name = node.name.lower()
        if name == "countdistinct":
            return self._visit_window_count_distinct(node)
        if node.args:
            self._unsupported(
                "TRINO_WINDOW_FUNCTION_PARAMETERS_UNSUPPORTED",
                f"Parametric window function '{node.name}' is not supported in Trino mode.",
                node,
            )
        if name == "laginframe":
            self._unsupported(
                "TRINO_LAG_IN_FRAME_UNSUPPORTED",
                "lagInFrame has no semantics-safe native Trino equivalent.",
                node,
            )
        exprs = [self.visit(expr) for expr in node.exprs or []]
        if name in _TRINO_CONDITIONAL_WINDOW_FUNCTIONS:
            if not exprs:
                self._unsupported(
                    "TRINO_WINDOW_FUNCTION_ARGUMENTS_UNSUPPORTED",
                    f"Window function '{node.name}' requires a condition in Trino mode.",
                    node,
                )
            target = _TRINO_CONDITIONAL_WINDOW_FUNCTIONS[name]
            arguments = exprs[:-1]
            if target == "count" and not arguments:
                call = f"count_if({exprs[-1]})"
            else:
                if len(arguments) != 1:
                    self._unsupported(
                        "TRINO_WINDOW_FUNCTION_ARGUMENTS_UNSUPPORTED",
                        f"Window function '{node.name}' requires one value and one condition in Trino mode.",
                        node,
                    )
                call = f"{target}(IF({exprs[-1]}, {arguments[0]}, NULL))"
        else:
            target = _TRINO_WINDOW_FUNCTION_RENAMES.get(name, name)
            if target not in _TRINO_WINDOW_FUNCTIONS:
                self._unsupported(
                    "TRINO_WINDOW_FUNCTION_UNSUPPORTED",
                    f"Window function '{node.name}' is not supported in Trino mode.",
                    node,
                )
            rendered_arguments = "*" if target == "count" and not exprs else ", ".join(exprs)
            call = f"{target}({rendered_arguments})"

        window_expr = self._window_expression(node)
        target = _TRINO_WINDOW_FUNCTION_RENAMES.get(name, name)
        if target in _TRINO_NO_FRAME_WINDOW_FUNCTIONS and window_expr is not None and window_expr.frame_method:
            self._unsupported(
                "TRINO_WINDOW_FRAME_UNSUPPORTED",
                f"Window function '{node.name}' does not allow an explicit frame in Trino mode.",
                node,
            )
        if target in {"lag", "lead"} and (window_expr is None or not window_expr.order_by):
            self._unsupported(
                "TRINO_WINDOW_ORDER_REQUIRED",
                f"Window function '{node.name}' requires ORDER BY in Trino mode.",
                node,
            )
        if node.over_expr:
            over = f"({self.visit(node.over_expr)})"
        elif node.over_identifier:
            over = self._print_identifier(node.over_identifier)
        else:
            over = "()"
        windowed_call = f"{call} OVER {over}"
        if name == "grouparrayif":
            value = self._print_identifier("__hogql_group_array_value")
            return f"filter({windowed_call}, {value} -> {value} IS NOT NULL)"
        return windowed_call

    def _window_expression(self, node: ast.WindowFunction) -> ast.WindowExpr | None:
        if node.over_expr is not None:
            return node.over_expr
        if node.over_identifier is None:
            return None
        select = self._last_select()
        if select is None or select.window_exprs is None:
            return None
        return select.window_exprs.get(node.over_identifier)

    def _visit_window_count_distinct(self, node: ast.WindowFunction) -> str:
        if node.exprs is None or len(node.exprs) != 1 or node.args:
            self._unsupported(
                "TRINO_WINDOW_FUNCTION_ARGUMENTS_UNSUPPORTED",
                "countDistinct window function expects exactly one argument in Trino mode.",
                node,
            )
        if node.over_expr:
            over = f"({self.visit(node.over_expr)})"
        elif node.over_identifier:
            over = self._print_identifier(node.over_identifier)
        else:
            over = "()"
        value = self._print_identifier("__hogql_count_distinct_value")
        values = f"array_agg({self.visit(node.exprs[0])}) OVER {over}"
        return f"cardinality(array_distinct(filter({values}, {value} -> {value} IS NOT NULL)))"

    def _get_compare_op(self, op: ast.CompareOperationOp, left: str, right: str) -> str:
        if op == ast.CompareOperationOp.ILike:
            return f"(lower({left}) LIKE lower({right}))"
        if op == ast.CompareOperationOp.NotILike:
            return f"(lower({left}) NOT LIKE lower({right}))"
        if op == ast.CompareOperationOp.Regex:
            return f"regexp_like({left}, {right})"
        if op == ast.CompareOperationOp.IRegex:
            return f"regexp_like({left}, '(?i)' || {right})"
        if op == ast.CompareOperationOp.NotRegex:
            return f"(NOT regexp_like({left}, {right}))"
        if op == ast.CompareOperationOp.NotIRegex:
            return f"(NOT regexp_like({left}, '(?i)' || {right}))"
        return super()._get_compare_op(op, left, right)

    def _visit_to_start_of_call(self, node: ast.Call) -> str:
        rendered = super()._visit_to_start_of_call(node)
        if isinstance(self._resolve_type(node), ast.DateType):
            return f"CAST({rendered} AS DATE)"
        return rendered

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        if unit == "week" and week_mode == 0:
            return f"date_add('day', -1, date_trunc('week', date_add('day', 1, {arg})))"
        if unit == "week" and week_mode not in {1, 3}:
            self._unsupported(
                "TRINO_START_OF_WEEK_MODE_UNSUPPORTED",
                f"Unsupported toStartOfWeek mode `{week_mode}` in Trino mode.",
            )
        if unit == "isoyear":
            self._unsupported("TRINO_START_OF_ISO_YEAR_UNSUPPORTED", "toStartOfISOYear is not supported in Trino mode.")
        return f"date_trunc('{unit}', {arg})"

    def _render_minute_bucket(self, arg: str, bucket_size: int) -> str:
        return (
            f"date_add('minute', CAST(floor(minute({arg}) / {bucket_size}) AS BIGINT) * {bucket_size}, "
            f"date_trunc('hour', {arg}))"
        )

    def visit_array_slice(self, node: ast.ArraySlice) -> str:
        start = self.visit(node.start_expr) if node.start_expr is not None else "1"
        if node.end_expr is None:
            length = "2147483647"
        else:
            end = self.visit(node.end_expr)
            length = f"greatest(0, ({end}) - ({start}) + 1)"
        return f"slice({self.visit(node.array)}, {start}, {length})"

    def visit_type_cast(self, node: ast.TypeCast) -> str:
        return f"CAST({self.visit(node.expr)} AS {self._trino_type(node.type_name)})"

    def visit_try_cast(self, node: ast.TryCast) -> str:
        return f"TRY_CAST({self.visit(node.expr)} AS {self._trino_type(node.type_name)})"

    def _trino_type(self, type_name: str) -> str:
        normalized = " ".join(type_name.strip().lower().split())
        target = _TRINO_SIMPLE_TYPES.get(normalized)
        if target is not None:
            return target
        if normalized.startswith("array(") and normalized.endswith(")"):
            return f"ARRAY({self._trino_type(normalized[6:-1])})"
        if normalized.startswith("map(") and normalized.endswith(")"):
            arguments = self._split_type_arguments(normalized[4:-1])
            if len(arguments) == 2:
                return f"MAP({self._trino_type(arguments[0])}, {self._trino_type(arguments[1])})"
        if normalized.startswith("nullable(") and normalized.endswith(")"):
            return self._trino_type(normalized[9:-1])
        match = _TRINO_PARAMETERIZED_TYPE_RE.fullmatch(normalized)
        if match is not None:
            base, parameters = match.groups()
            values = [int(parameter.strip()) for parameter in parameters.split(",")]
            normalized_base = base.lower()
            if normalized_base in {"decimal", "numeric"}:
                precision = values[0]
                scale = values[1] if len(values) == 2 else 0
                if len(values) > 2 or not 1 <= precision <= 38 or not 0 <= scale <= precision:
                    self._unsupported(
                        "TRINO_CAST_TYPE_UNSUPPORTED", f"Type '{type_name}' is not supported in Trino mode."
                    )
                rendered_parameters = str(precision) if len(values) == 1 else f"{precision},{scale}"
                return f"DECIMAL({rendered_parameters})"
            if normalized_base in {"datetime64", "timestamp"}:
                if len(values) != 1 or not 0 <= values[0] <= 12:
                    self._unsupported(
                        "TRINO_CAST_TYPE_UNSUPPORTED", f"Type '{type_name}' is not supported in Trino mode."
                    )
                return f"TIMESTAMP({values[0]})"
            if len(values) != 1 or values[0] < 1:
                self._unsupported("TRINO_CAST_TYPE_UNSUPPORTED", f"Type '{type_name}' is not supported in Trino mode.")
            rendered_base = "CHAR" if normalized_base == "fixedstring" else normalized_base.upper()
            return f"{rendered_base}({values[0]})"
        self._unsupported("TRINO_CAST_TYPE_UNSUPPORTED", f"Type '{type_name}' is not supported in Trino mode.")

    @staticmethod
    def _split_type_arguments(arguments: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        start = 0
        for index, character in enumerate(arguments):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character == "," and depth == 0:
                parts.append(arguments[start:index].strip())
                start = index + 1
        parts.append(arguments[start:].strip())
        return parts

    def _unsafe_json_extract_trim_quotes(self, unsafe_field: str, unsafe_args: list[str]) -> str:
        if not unsafe_args:
            return unsafe_field
        if len(unsafe_args) != 1:
            self._unsupported(
                "TRINO_JSON_PROPERTY_NOT_LOWERED",
                "Nested JSON property access must be lowered before Trino printing.",
            )
        return f"json_extract_scalar({unsafe_field}, {unsafe_args[0]})"

    def _json_property_args(self, chain: Iterable[str | int]) -> list[str]:
        return [self._json_path(chain)]

    def _assert_qualify_supported(self) -> None:
        self._unsupported("TRINO_QUALIFY_NOT_LOWERED", "QUALIFY must be lowered before Trino printing.")

    def _assert_with_ties_supported(self) -> None:
        self._unsupported("TRINO_WITH_TIES_NOT_LOWERED", "WITH TIES must be lowered before Trino printing.")

    def visit_cte(self, node: ast.CTE) -> str:
        if node.materialized is not None or node.using_key is not None:
            self._unsupported(
                "TRINO_CTE_MODIFIER_UNSUPPORTED",
                "CTE materialization hints and USING KEY are not supported in Trino mode.",
                node,
            )
        return super().visit_cte(node)
