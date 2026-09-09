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
        "stddev_pop",
    }
)
_TRINO_WINDOW_FUNCTION_RENAMES = {
    "any": "arbitrary",
    "anylast": "arbitrary",
    "argmax": "max_by",
    "argmin": "min_by",
    "grouparray": "array_agg",
    "stddevpop": "stddev_pop",
}
_TRINO_CONDITIONAL_WINDOW_FUNCTIONS = {
    "anyif": "arbitrary",
    "avgif": "avg",
    "countif": "count",
    "grouparrayif": "array_agg",
    "maxif": "max",
    "minif": "min",
    "sumif": "sum",
    "stddevpopif": "stddev_pop",
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

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> str:
        node = self._align_set_query_types(node)
        first = node.initial_select_query
        if isinstance(first, ast.SelectQuery) and first.ctes:
            ctes = first.ctes
            first.ctes = None
            try:
                prefix = ", ".join(self.visit(cte) for cte in ctes.values())
                body = super().visit_select_set_query(node)
                if len(self.stack) > 1:
                    return f"(WITH {prefix} {body[1:-1]})"
                return f"WITH {prefix} {body}"
            finally:
                first.ctes = ctes
        return super().visit_select_set_query(node)

    def _align_set_query_types(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        branches = node.select_queries()
        if not branches:
            return node
        width = min(len(branch.select) for branch in branches)
        targets: dict[int, str] = {}
        for index in range(width):
            expressions = [
                projection.expr if isinstance(projection := branch.select[index], ast.Alias) else projection
                for branch in branches
            ]
            types = [self._resolve_type(expression) for expression in expressions]
            if any(isinstance(value_type, ast.StringType) for value_type in types) and any(
                isinstance(
                    value_type,
                    (ast.IntegerType, ast.FloatType, ast.DecimalType, ast.BooleanType, ast.UUIDType),
                )
                for value_type in types
            ):
                targets[index] = "varchar"
            elif any(isinstance(value_type, ast.BooleanType) for value_type in types) and any(
                isinstance(value_type, (ast.IntegerType, ast.FloatType, ast.DecimalType)) for value_type in types
            ):
                targets[index] = "bigint"
        if not targets:
            return node
        lowered = clone_expr(node, clear_types=False)
        for branch in lowered.select_queries():
            for index, target in targets.items():
                projection = branch.select[index]
                expression = projection.expr if isinstance(projection, ast.Alias) else projection
                source_type = self._resolve_type(expression)
                cast_expression: ast.Expr = (
                    ast.Call(name="toJSONString", args=[expression])
                    if target == "varchar" and isinstance(source_type, (ast.ArrayType, ast.MapType, ast.TupleType))
                    else ast.TypeCast(expr=expression, type_name=target)
                )
                if isinstance(projection, ast.Alias):
                    projection.expr = cast_expression
                else:
                    branch.select[index] = cast_expression
        return lowered

    def visit_alias(self, node: ast.Alias) -> str:
        parent = self.stack[-2] if len(self.stack) > 1 else None
        if isinstance(parent, ast.SelectQuery) and any(expr is node for expr in parent.select):
            return super().visit_alias(node)
        return self.visit(node.expr)

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
        comparison_operators = {
            "equals": ast.CompareOperationOp.Eq,
            "notequals": ast.CompareOperationOp.NotEq,
            "greater": ast.CompareOperationOp.Gt,
            "greaterorequals": ast.CompareOperationOp.GtEq,
            "less": ast.CompareOperationOp.Lt,
            "lessorequals": ast.CompareOperationOp.LtEq,
        }
        if name in comparison_operators:
            if len(node.args) != 2:
                self._invalid_function_arguments(node, f"{node.name} expects exactly 2 arguments in Trino mode.")
            return self.visit_compare_operation(
                ast.CompareOperation(op=comparison_operators[name], left=node.args[0], right=node.args[1])
            )
        if name in {"if", "multiif"}:
            if len(node.args) < 3 or len(node.args) % 2 == 0 or (name == "if" and len(node.args) != 3):
                self._invalid_function_arguments(node, f"{node.name} expects condition/value pairs and a default.")
            cases = [
                f"WHEN {self._visit_predicate(node.args[index])} THEN {self.visit(node.args[index + 1])}"
                for index in range(0, len(node.args) - 1, 2)
            ]
            return f"CASE {' '.join(cases)} ELSE {self.visit(node.args[-1])} END"
        if (
            name in {"countif", "countdistinctif", "uniqif", "uniqexactif", "sumif", "avgif", "minif", "maxif", "anyif"}
            and node.args
        ):
            if self._is_numeric(node.args[-1]) or self._is_dynamic_property(node.args[-1]):
                lowered = clone_expr(node, clear_types=False)
                lowered.args[-1] = ast.TypeCast(expr=lowered.args[-1], type_name="boolean")
                return super().visit_call(lowered)
        if (
            name in {"coalesce", "ifnull", "nullif"}
            and any(isinstance(self._resolve_type(arg), ast.BooleanType) for arg in node.args)
            and any(self._is_dynamic_property(arg) for arg in node.args)
        ):
            lowered = clone_expr(node, clear_types=False)
            lowered.args = [
                ast.TypeCast(expr=arg, type_name="boolean") if self._is_dynamic_property(arg) else arg
                for arg in lowered.args
            ]
            return self.visit_call(lowered)
        if (
            name in {"coalesce", "ifnull", "nullif"}
            and any(isinstance(self._resolve_type(arg), ast.BooleanType) for arg in node.args)
            and any(self._is_numeric(arg) for arg in node.args)
        ):
            coerced_args = [
                f"CAST({self.visit(arg)} AS INTEGER)"
                if isinstance(self._resolve_type(arg), ast.BooleanType)
                else self.visit(arg)
                for arg in node.args
            ]
            function = "nullif" if name == "nullif" else "coalesce"
            return f"{function}({', '.join(coerced_args)})"
        if (
            name in {"coalesce", "ifnull", "nullif"}
            and any(isinstance(self._resolve_type(arg), ast.StringType) for arg in node.args)
            and any(self._is_numeric(arg) for arg in node.args)
        ):
            coerced_args = [
                self.visit(arg)
                if isinstance(self._resolve_type(arg), ast.StringType)
                else f"CAST({self.visit(arg)} AS VARCHAR)"
                for arg in node.args
            ]
            function = "nullif" if name == "nullif" else "coalesce"
            return f"{function}({', '.join(coerced_args)})"
        if (
            name == "tostring"
            and len(node.args) == 1
            and isinstance(self._resolve_type(node.args[0]), (ast.ArrayType, ast.MapType, ast.TupleType))
        ):
            return f"json_format(CAST({self.visit(node.args[0])} AS JSON))"
        if name in {"empty", "notempty"}:
            return self._visit_empty(node, negated=name == "notempty")
        if name in {"in", "notin"} and len(node.args) == 2 and isinstance(node.args[1], ast.Array):
            result = f"contains({self.visit(node.args[1])}, {self.visit(node.args[0])})"
            return f"NOT ({result})" if name == "notin" else result
        if name in {"in", "notin"} and len(node.args) == 2 and isinstance(node.args[1], ast.Tuple):
            values = ", ".join(self.visit(value) for value in node.args[1].exprs)
            return f"({self.visit(node.args[0])} {'NOT IN' if name == 'notin' else 'IN'} ({values}))"
        if (
            name in {"in", "notin"}
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Call)
            and node.args[1].name.lower() == "tuple"
        ):
            values = ", ".join(self.visit(value) for value in node.args[1].args)
            return f"({self.visit(node.args[0])} {'NOT IN' if name == 'notin' else 'IN'} ({values}))"
        if name in {"in", "notin"}:
            binary_args = self._visit_binary_args(node)
            return f"({binary_args.left} {'NOT IN' if name == 'notin' else 'IN'} {binary_args.right})"
        if name == "arraymax":
            return self._visit_unary_function(node, "array_max")
        if name == "arrayenumerate":
            value = self._visit_unary_arg(node)
            return f"IF(cardinality({value}) = 0, CAST(ARRAY[] AS ARRAY(BIGINT)), sequence(1, cardinality({value})))"
        if name == "arrayexists":
            return self._visit_lambda_array_call(node, "any_match")
        if name == "intdiv":
            binary_args = self._visit_binary_args(node)
            if not all(isinstance(self._resolve_type(arg), ast.IntegerType) for arg in node.args):
                self._unsupported(
                    "TRINO_INT_DIV_TYPE_UNSUPPORTED", "intDiv requires integer operands in Trino mode.", node
                )
            return f"(CAST({binary_args.left} AS BIGINT) / CAST({binary_args.right} AS BIGINT))"
        if name == "roundbankers":
            return self._visit_round_bankers(node)
        if name == "extracturlparameter":
            binary_args = self._visit_binary_args(node)
            without_fragment = f"split_part({binary_args.left}, '#', 1)"
            query = f"IF(strpos({without_fragment}, '?') > 0, substr({without_fragment}, strpos({without_fragment}, '?') + 1), '')"
            parameter = f"element_at(filter(split({query}, '&'), __hogql_parameter -> split_part(__hogql_parameter, '=', 1) = {binary_args.right}), 1)"
            return f"coalesce(substr({parameter}, length({binary_args.right}) + 2), '')"
        if name == "arrayzip":
            if not 2 <= len(node.args) <= 5 or not all(isinstance(arg, ast.Array) for arg in node.args):
                self._unsupported(
                    "TRINO_ARRAY_ZIP_DYNAMIC_UNSUPPORTED",
                    "arrayZip requires two to five explicit equal-length arrays in Trino mode.",
                    node,
                )
            arrays = [arg for arg in node.args if isinstance(arg, ast.Array)]
            if len({len(arg.exprs) for arg in arrays}) != 1:
                self._invalid_function_arguments(node, "arrayZip requires equal-length arrays.")
            return f"zip({', '.join(self.visit(arg) for arg in arrays)})"
        if name in {"extractallgroups", "replaceregexpone"}:
            return self._visit_constant_regex(node)
        if name == "median":
            if node.distinct or node.order_by or node.filter_expr or node.params:
                self._unsupported(
                    "TRINO_MEDIAN_MODIFIER_UNSUPPORTED", "median modifiers are not supported in Trino mode.", node
                )
            return f"approx_percentile({self._visit_unary_arg(node)}, 0.5)"
        if name == "quantileexact":
            return self._visit_quantile(node, filtered=False)
        if name == "aggregate_funnel_trends":
            if len(node.args) != 8:
                self._invalid_function_arguments(node, "aggregate_funnel_trends expects exactly 8 arguments.")
            events = self.visit(node.args[-1])
            return (
                f"transform(slice({events}, 1, 1), __event -> "
                "ROW(CAST(__event[2] AS BIGINT), "
                "CAST(IF(contains(__event[5], 2), 1, 0) AS BIGINT), CAST(__event[4] AS VARCHAR)))"
            )
        if name == "cityhash64":
            value = self._visit_unary_arg(node)
            return f"from_big_endian_64(xxhash64(to_utf8(CAST({value} AS VARCHAR))))"
        if name == "hex":
            value = self._visit_unary_arg(node)
            return f"to_hex(to_utf8(CAST({value} AS VARCHAR)))"
        if name == "ngramdistance":
            binary_args = self._visit_binary_args(node)
            maximum = f"greatest(length({binary_args.left}), length({binary_args.right}), 1)"
            return f"(CAST(levenshtein_distance({binary_args.left}, {binary_args.right}) AS DOUBLE) / {maximum})"
        if name == "touuidordefault":
            binary_args = self._visit_binary_args(node)
            return f"coalesce(TRY_CAST({binary_args.left} AS UUID), TRY_CAST({binary_args.right} AS UUID))"
        if name == "reinterpretasuuid":
            value = self._visit_unary_arg(node)
            return f"TRY_CAST(CAST({value} AS VARCHAR) AS UUID)"
        if name == "cuttofirstsignificantsubdomain":
            value = self._visit_unary_arg(node)
            labels = f"filter(split(lower(trim(TRAILING '.' FROM {value})), '.'), __hogql_label -> __hogql_label <> '')"
            return f"array_join(slice({labels}, greatest(cardinality({labels}) - 1, 1), 2), '.')"
        if name in {"floor", "ceil"} and len(node.args) == 2:
            binary_args = self._visit_binary_args(node)
            scale = f"power(10, {binary_args.right})"
            return f"({name}({binary_args.left} * {scale}) / {scale})"
        if name == "tostartofinterval":
            return self._visit_start_of_interval(node)
        if name == "mapfromarrays":
            return self._visit_map_from_arrays(node)
        if name in {"datediff", "date_diff"} and len(node.args) == 3:
            unit_expr = node.args[0]
            if isinstance(unit_expr, ast.Constant) and isinstance(unit_expr.value, str):
                unit_expr = ast.Constant(value=unit_expr.value.lower().removesuffix("s"))
            rendered_args = [self.visit(unit_expr)]
            for arg in node.args[1:]:
                value = self.visit(arg)
                rendered_args.append(
                    f"CAST({value} AS TIMESTAMP)" if isinstance(self._resolve_type(arg), ast.StringType) else value
                )
            return f"date_diff({', '.join(rendered_args)})"
        if name == "length" and node.args and isinstance(self._resolve_type(node.args[0]), ast.ArrayType):
            return self._visit_unary_function(node, "cardinality")
        if name in {"sum", "avg"} and len(node.args) == 1 and not self._is_dynamic_property(node.args[0]):
            arg_type = self._resolve_type(node.args[0])
            if isinstance(arg_type, ast.StringType):
                lowered = clone_expr(node, clear_types=False)
                lowered.args[0] = ast.TryCast(expr=lowered.args[0], type_name="double")
                return super().visit_call(lowered)
            if isinstance(arg_type, ast.BooleanType):
                lowered = clone_expr(node, clear_types=False)
                lowered.args[0] = ast.TypeCast(expr=lowered.args[0], type_name="bigint")
                return super().visit_call(lowered)
        if name in {"toint", "tointorzero", "tointordefault", "_touint64"} and node.args:
            arg = node.args[0]
            arg_type = arg.type.resolve_constant_type(self.context) if arg.type is not None else None
            rendered = self.visit(arg)
            if isinstance(arg_type, ast.DateType):
                return f"date_diff('day', DATE '1970-01-01', {rendered})"
            if isinstance(arg_type, ast.DateTimeType):
                return f"CAST(to_unixtime({rendered}) AS BIGINT)"
            if isinstance(arg_type, ast.BooleanType):
                return f"CASE WHEN {rendered} THEN 1 ELSE 0 END"
            if name == "toint" and isinstance(arg_type, ast.StringType):
                return f"TRY_CAST({rendered} AS BIGINT)"
        if name in {"tofloat", "tofloatorzero", "tofloatordefault"} and node.args:
            arg = node.args[0]
            arg_type = self._resolve_type(arg)
            if isinstance(arg_type, ast.DateType):
                return f"CAST(date_diff('day', DATE '1970-01-01', {self.visit(arg)}) AS DOUBLE)"
            if isinstance(arg_type, ast.DateTimeType):
                return f"to_unixtime({self.visit(arg)})"
        if (
            re.fullmatch(r"(?:add|subtract)(?:Seconds|Minutes|Hours|Days|Weeks|Months|Quarters|Years)", node.name)
            and node.args
            and isinstance(self._resolve_type(node.args[0]), ast.StringType)
        ):
            subtract = node.name.startswith("subtract")
            unit_name = node.name[8 if subtract else 3 : -1].lower()
            amount = self.visit(node.args[1])
            if subtract:
                amount = f"-({amount})"
            return f"date_add('{unit_name}', {amount}, CAST({self.visit(node.args[0])} AS TIMESTAMP))"
        if name == "tounixtimestamp" and node.args and self._is_numeric(node.args[0]):
            return f"CAST({self.visit(node.args[0])} AS BIGINT)"
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
            if self._is_numeric(value_expr) or (
                isinstance(value_expr, ast.Call)
                and value_expr.name.lower() == "tostring"
                and value_expr.args
                and self._is_numeric(value_expr.args[0])
            ):
                timestamp = f"from_unixtime(CAST({self.visit(value_expr)} AS DOUBLE))"
                return (
                    f"at_timezone({timestamp}, {self.visit(node.args[1])})"
                    if len(node.args) == 2
                    else f"CAST({timestamp} AS TIMESTAMP)"
                )
            if isinstance(self._resolve_type(value_expr), ast.StringType) and not isinstance(value_expr, ast.Constant):
                value = self.visit(value_expr)
                timestamp = f"coalesce(TRY_CAST({value} AS TIMESTAMP), CAST(TRY(from_iso8601_timestamp({value})) AS TIMESTAMP), CAST(from_unixtime(TRY_CAST({value} AS DOUBLE)) AS TIMESTAMP))"
                return f"with_timezone({timestamp}, {self.visit(node.args[1])})" if len(node.args) == 2 else timestamp
            if len(node.args) == 2:
                return f"with_timezone(CAST({self.visit(value_expr)} AS TIMESTAMP), {self.visit(node.args[1])})"
        if name == "totimezone":
            binary_args = self._visit_binary_args(node)
            return f"at_timezone(with_timezone(CAST({binary_args.left} AS TIMESTAMP), 'UTC'), {binary_args.right})"
        if name == "parsedatetime":
            return self._visit_parse_datetime(node)
        if name == "parsedatetimebesteffort":
            return self._visit_parse_datetime_best_effort(node)
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
        if name == "arraycount":
            return f"cardinality({self._visit_lambda_array_call(node, 'filter')})"
        if name == "countequal":
            binary_args = self._visit_binary_args(node)
            return (
                f"element_at(transform(ARRAY[ROW({binary_args.left}, {binary_args.right})], __hogql_args -> "
                "cardinality(filter(__hogql_args[1], __hogql_item -> "
                "__hogql_item IS NOT DISTINCT FROM __hogql_args[2]))), 1)"
            )
        if name == "multisearchanycaseinsensitive":
            binary_args = self._visit_binary_args(node)
            return f"any_match({binary_args.right}, __hogql_needle -> strpos(lower({binary_args.left}), lower(__hogql_needle)) > 0)"
        if name == "arrayelement":
            return self._visit_binary_function(node, "element_at")
        if name == "arraydistinct":
            return self._visit_unary_function(node, "array_distinct")
        if name == "extractall":
            if len(node.args) != 2:
                self._invalid_function_arguments(node, "extractAll expects exactly 2 arguments in Trino mode.")
            return f"regexp_extract_all({self.visit(node.args[0])}, {self.visit(node.args[1])}, 1)"
        if name == "arraysort":
            if len(node.args) == 2 and isinstance(node.args[0], ast.Lambda):
                return self._visit_array_sort_key(node)
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
            value = self._visit_unary_arg(node)
            return f"reduce({value}, CAST(0 AS DOUBLE), (s, x) -> s + coalesce(CAST(x AS DOUBLE), 0), s -> s)"
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
            rendered_args = [self.visit(arg) for arg in node.args]
            target = "max_by" if name == "argmaxif" else "min_by"
            return f"{target}({rendered_args[0]}, {rendered_args[1]}) FILTER (WHERE {rendered_args[2]})"
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
            if len(node.args) == 3:
                separator, value, maximum = (self.visit(arg) for arg in node.args)
                split = f"split({value}, {separator})"
                return f"CASE WHEN {maximum} = 0 THEN {split} ELSE slice({split}, 1, {maximum}) END"
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

    def _visit_predicate(self, node: ast.Expr) -> str:
        rendered = self.visit(node)
        return f"CAST({rendered} AS BOOLEAN)" if self._is_numeric(node) or self._is_dynamic_property(node) else rendered

    def visit_and(self, node: ast.And) -> str:
        return "(" + " AND ".join(f"({self._visit_predicate(expr)})" for expr in node.exprs) + ")"

    def visit_or(self, node: ast.Or) -> str:
        return "(" + " OR ".join(f"({self._visit_predicate(expr)})" for expr in node.exprs) + ")"

    def visit_not(self, node: ast.Not) -> str:
        return f"(NOT {self._visit_predicate(node.expr)})"

    def visit_compare_operation(self, node: ast.CompareOperation) -> str:
        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn) and isinstance(node.right, ast.Array):
            result = f"contains({self.visit(node.right)}, {self.visit(node.left)})"
            return f"NOT ({result})" if node.op == ast.CompareOperationOp.NotIn else result
        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn) and isinstance(node.right, ast.Tuple):
            values = ", ".join(self.visit(value) for value in node.right.exprs)
            return self._get_compare_op(node.op, self.visit(node.left), f"({values})")
        if (
            node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn)
            and isinstance(node.right, ast.Call)
            and node.right.name.lower() == "tuple"
        ):
            values = ", ".join(self.visit(value) for value in node.right.args)
            return self._get_compare_op(node.op, self.visit(node.left), f"({values})")
        if (
            isinstance(self._resolve_type(node.left), ast.ArrayType)
            and isinstance(node.right, ast.Constant)
            and node.right.value == "[]"
            and node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq)
        ):
            return self._get_compare_op(node.op, f"cardinality({self.visit(node.left)})", "0")
        left_type = self._resolve_type(node.left)
        right_type = self._resolve_type(node.right)
        if node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn) and isinstance(
            node.right, (ast.SelectQuery, ast.SelectSetQuery)
        ):
            right_scalar_type = self._subquery_scalar_type(node.right)
            if self._is_dynamic_property(node.left) and isinstance(
                right_scalar_type, (ast.IntegerType, ast.FloatType, ast.DecimalType)
            ):
                target = "BIGINT" if isinstance(right_scalar_type, ast.IntegerType) else "DOUBLE"
                return self._get_compare_op(
                    node.op, f"TRY_CAST({self.visit(node.left)} AS {target})", self.visit(node.right)
                )
            if isinstance(left_type, ast.StringType) and isinstance(
                right_scalar_type, (ast.IntegerType, ast.FloatType, ast.DecimalType)
            ):
                target = "BIGINT" if isinstance(right_scalar_type, ast.IntegerType) else "DOUBLE"
                return self._get_compare_op(
                    node.op, f"TRY_CAST({self.visit(node.left)} AS {target})", self.visit(node.right)
                )
            if self._is_numeric(node.left) and isinstance(right_scalar_type, ast.StringType):
                return self._get_compare_op(
                    node.op,
                    f"CAST({self.visit(node.left)} AS VARCHAR)",
                    self.visit(node.right),
                )
        if (
            node.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn)
            and isinstance(node.right, ast.Tuple)
            and isinstance(left_type, (ast.DateType, ast.DateTimeType))
        ):
            target = "DATE" if isinstance(left_type, ast.DateType) else "TIMESTAMP"
            values = ", ".join(f"CAST({self.visit(value)} AS {target})" for value in node.right.exprs)
            return self._get_compare_op(node.op, self.visit(node.left), f"({values})")
        left_cast: str | None = None
        right_cast: str | None = None

        if isinstance(left_type, ast.UUIDType) and isinstance(right_type, ast.StringType):
            left_cast = "VARCHAR"
        elif isinstance(right_type, ast.UUIDType) and isinstance(left_type, ast.StringType):
            right_cast = "VARCHAR"
        elif isinstance(left_type, ast.DateTimeType) and isinstance(right_type, ast.StringType):
            right_cast = "TIMESTAMP"
        elif isinstance(right_type, ast.DateTimeType) and isinstance(left_type, ast.StringType):
            left_cast = "TIMESTAMP"
        elif isinstance(left_type, ast.DateType) and isinstance(right_type, ast.StringType):
            right_cast = "DATE"
        elif isinstance(right_type, ast.DateType) and isinstance(left_type, ast.StringType):
            left_cast = "DATE"
        elif isinstance(left_type, ast.DateTimeType) and isinstance(
            right_type, (ast.IntegerType, ast.FloatType, ast.DecimalType)
        ):
            right = f"from_unixtime(CAST({self.visit(node.right)} AS DOUBLE))"
            return self._get_compare_op(node.op, self.visit(node.left), right)
        elif isinstance(right_type, ast.DateTimeType) and isinstance(
            left_type, (ast.IntegerType, ast.FloatType, ast.DecimalType)
        ):
            left = f"from_unixtime(CAST({self.visit(node.left)} AS DOUBLE))"
            return self._get_compare_op(node.op, left, self.visit(node.right))
        elif self._is_dynamic_property(node.left) and isinstance(right_type, ast.BooleanType):
            left_cast = "BOOLEAN"
        elif self._is_dynamic_property(node.right) and isinstance(left_type, ast.BooleanType):
            right_cast = "BOOLEAN"
        elif isinstance(left_type, ast.StringType) and isinstance(right_type, ast.BooleanType):
            left_cast = "BOOLEAN"
        elif isinstance(right_type, ast.StringType) and isinstance(left_type, ast.BooleanType):
            right_cast = "BOOLEAN"
        elif isinstance(left_type, ast.BooleanType) and isinstance(right_type, ast.IntegerType):
            left_cast = "INTEGER"
        elif isinstance(right_type, ast.BooleanType) and isinstance(left_type, ast.IntegerType):
            right_cast = "INTEGER"
        elif self._is_numeric(node.left) and isinstance(right_type, ast.StringType):
            right_cast = "BIGINT" if isinstance(left_type, ast.IntegerType) else "DOUBLE"
        elif self._is_numeric(node.right) and isinstance(left_type, ast.StringType):
            left_cast = "BIGINT" if isinstance(right_type, ast.IntegerType) else "DOUBLE"
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
        if (
            node.op in (ast.ArithmeticOperationOp.Add, ast.ArithmeticOperationOp.Sub)
            and self._is_numeric(node.right)
            and isinstance(self._resolve_type(node.left), (ast.DateType, ast.DateTimeType))
        ):
            unit = "day" if isinstance(self._resolve_type(node.left), ast.DateType) else "second"
            amount = f"-({right})" if node.op == ast.ArithmeticOperationOp.Sub else right
            return f"date_add('{unit}', CAST({amount} AS BIGINT), {left})"
        lowered = False
        if isinstance(self._resolve_type(node.left), ast.BooleanType):
            left = f"CAST({left} AS INTEGER)"
            lowered = True
        if isinstance(self._resolve_type(node.right), ast.BooleanType):
            right = f"CAST({right} AS INTEGER)"
            lowered = True
        if (
            isinstance(node.right, ast.Call)
            and node.right.name.lower().startswith("tointerval")
            and isinstance(self._resolve_type(node.left), ast.StringType)
        ):
            left = f"CAST({left} AS TIMESTAMP)"
            lowered = True
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
        if isinstance(node, ast.Call) and node.name.lower() in {"jsonhas", "multisearchanycaseinsensitive"}:
            return ast.BooleanType()
        if isinstance(node, ast.Call) and node.name.lower() in {"coalesce", "ifnull", "nullif"}:
            if any(isinstance(self._resolve_type(arg), ast.BooleanType) for arg in node.args) and any(
                self._is_numeric(arg) for arg in node.args
            ):
                return ast.IntegerType()
            if any(isinstance(self._resolve_type(arg), ast.BooleanType) for arg in node.args) and any(
                self._is_dynamic_property(arg) for arg in node.args
            ):
                return ast.BooleanType()
        value_type = node.type
        seen: set[int] = set()
        while value_type is not None and id(value_type) not in seen:
            seen.add(id(value_type))
            if isinstance(value_type, ast.FieldAliasType):
                value_type = value_type.type
                continue
            if isinstance(value_type, ast.FieldType):
                table_type = value_type.table_type
                if isinstance(table_type, ast.CTETableAliasType):
                    table_type = table_type.cte_table_type
                if isinstance(table_type, ast.CTETableType) and isinstance(
                    table_type.select_query_type, ast.SelectQueryType
                ):
                    column_type = table_type.select_query_type.columns.get(value_type.name)
                    if column_type is not None:
                        value_type = column_type
                        continue
            break
        if isinstance(value_type, ast.CallType) and value_type.name.lower() == "jsonextractarrayraw":
            return ast.ArrayType(item_type=ast.StringType())
        resolved = value_type.resolve_constant_type(self.context) if value_type is not None else None
        if isinstance(resolved, ast.StringArrayType):
            return ast.ArrayType(item_type=ast.StringType(), nullable=resolved.nullable)
        return resolved

    def _subquery_scalar_type(self, node: ast.SelectQuery | ast.SelectSetQuery) -> ast.ConstantType | None:
        query = node
        while isinstance(query, ast.SelectSetQuery):
            query = query.initial_select_query
        if not query.select:
            return None
        expression = query.select[0]
        while isinstance(expression, ast.Alias):
            expression = expression.expr
        return self._resolve_type(expression)

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
        if not node.args or (name == "jsonextract" and len(node.args) < 2):
            self._invalid_function_arguments(node, f"{node.name} expects a JSON expression and key path in Trino mode.")
        if name == "jsonextract":
            return self._visit_typed_json_extract(node)
        if any(not isinstance(key, ast.Constant) for key in node.args[1:]):
            extracted = self.visit(node.args[0])
            for key in node.args[1:]:
                if isinstance(key, ast.Constant) and isinstance(key.value, (str, int)):
                    path = self._json_path([key.value])
                else:
                    path = self._dynamic_json_key_path(key)
                extracted = f"json_extract({extracted}, {path})"
            if name == "jsonextractraw":
                return f"json_format({extracted})"
            scalar = f"json_extract_scalar({extracted}, '$')"
            casts = {
                "jsonextractint": "BIGINT",
                "jsonextractuint": "DECIMAL(20, 0)",
                "jsonextractfloat": "DOUBLE",
                "jsonextractbool": "BOOLEAN",
            }
            target_type = casts.get(name)
            return scalar if target_type is None else f"CAST({scalar} AS {target_type})"
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
        if name == "jsonextractarrayraw":
            value = self._print_identifier("__hogql_json_value")
            return f"transform(CAST({extracted} AS ARRAY(JSON)), {value} -> json_format({value}))"
        if name == "jsonextractraw":
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
        if target.startswith("MAP(VARCHAR, "):
            value_type = target[len("MAP(VARCHAR, ") : -1]
            if value_type in {
                "VARCHAR",
                "BOOLEAN",
                "REAL",
                "DOUBLE",
                "TINYINT",
                "SMALLINT",
                "INTEGER",
                "BIGINT",
                "DECIMAL(20, 0)",
            }:
                raw = f"CAST(json_extract({source}, {path}) AS MAP(VARCHAR, JSON))"
                converted = self._convert_json_scalar("__hogql_json_value", value_type)
                if "nullable(" not in type_arg.value.lower():
                    default = "''" if value_type == "VARCHAR" else "false" if value_type == "BOOLEAN" else "0"
                    converted = f"coalesce({converted}, CAST({default} AS {value_type}))"
                return f"transform_values({raw}, (__hogql_json_key, __hogql_json_value) -> {converted})"
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
        if name == "jsonhas" and any(not isinstance(key, ast.Constant) for key in path_args):
            extracted = source
            for key in path_args:
                if isinstance(key, ast.Constant) and isinstance(key.value, (str, int)):
                    path = self._json_path([key.value])
                else:
                    path = self._dynamic_json_key_path(key)
                extracted = f"json_extract({extracted}, {path})"
            return f"({extracted} IS NOT NULL)"
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
            raw = f"CAST(json_extract({source}, {path}) AS MAP(VARCHAR, JSON))"
            value = "__hogql_json_value"
            assert target_type is not None
            converted = self._convert_json_scalar(value, target_type)
            return (
                f"filter(map_entries(transform_values({raw}, (__hogql_json_key, {value}) -> {converted})), "
                "__hogql_entry -> __hogql_entry[2] IS NOT NULL)"
            )
        return f"map_keys(CAST(json_extract({source}, {path}) AS MAP(VARCHAR, JSON)))"

    def _convert_json_scalar(self, value: str, target_type: str) -> str:
        if target_type == "VARCHAR":
            converted = f"coalesce(TRY_CAST({value} AS VARCHAR), json_format({value}))"
            return f"IF(json_format({value}) = 'null', NULL, {converted})"
        converted = f"TRY_CAST({value} AS {target_type})"
        if target_type != "BOOLEAN":
            return (
                f"CASE json_format({value}) WHEN 'true' THEN CAST(1 AS {target_type}) "
                f"WHEN 'false' THEN CAST(0 AS {target_type}) ELSE {converted} END"
            )
        return converted

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

    def _visit_parse_datetime_best_effort(self, node: ast.Call) -> str:
        if len(node.args) not in {1, 2}:
            self._invalid_function_arguments(node, "parseDateTimeBestEffort expects a string and optional timezone.")
        value = self.visit(node.args[0])
        timezone = self.visit(node.args[1]) if len(node.args) == 2 else self.context.add_value(self._get_timezone())
        day_month_year = self.context.add_value("%e-%b-%y")
        parsed = (
            f"coalesce(IF(regexp_like({value}, '(Z|[+-][0-9]{{2}}:[0-9]{{2}})$'), TRY(from_iso8601_timestamp({value}))), "
            f"IF(regexp_like({value}, '^[0-9]{{9,10}}$'), from_unixtime(TRY_CAST({value} AS DOUBLE))), "
            f"with_timezone(TRY(date_parse({value}, {day_month_year})), {timezone}), "
            f"with_timezone(CAST({value} AS TIMESTAMP), {timezone}))"
        )
        return f"CAST(at_timezone({parsed}, {timezone}) AS TIMESTAMP)"

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

    def _dynamic_json_key_path(self, key: ast.Expr) -> str:
        return f"concat('$[', json_format(CAST(CAST({self.visit(key)} AS VARCHAR) AS JSON)), ']')"

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

    def _visit_array_sort_key(self, node: ast.Call) -> str:
        key = node.args[0]
        if not isinstance(key, ast.Lambda) or len(key.args) != 1:
            self._invalid_function_arguments(node, "arraySort expects a single-argument key lambda and array.")
        arg = self._print_identifier(key.args[0])
        keyed = f"transform({self.visit(node.args[1])}, {arg} -> ROW({self.visit(key.expr)}, {arg}))"
        return (
            f"transform(array_sort({keyed}, (__hogql_left, __hogql_right) -> "
            "CASE WHEN __hogql_left[1] IS NULL AND __hogql_right[1] IS NULL THEN 0 "
            "WHEN __hogql_left[1] IS NULL THEN 1 WHEN __hogql_right[1] IS NULL THEN -1 "
            "WHEN __hogql_left[1] < __hogql_right[1] THEN -1 "
            "WHEN __hogql_left[1] > __hogql_right[1] THEN 1 ELSE 0 END), __hogql_pair -> __hogql_pair[2])"
        )

    def _visit_start_of_interval(self, node: ast.Call) -> str:
        if len(node.args) != 2 or not isinstance(node.args[1], ast.Call):
            self._invalid_function_arguments(node, "toStartOfInterval expects a timestamp and constant interval.")
        interval = node.args[1]
        units = {"tointervalsecond": 1, "tointervalminute": 60}
        unit = units.get(interval.name.lower())
        if (
            unit is None
            or len(interval.args) != 1
            or not isinstance(interval.args[0], ast.Constant)
            or not isinstance(interval.args[0].value, int)
            or interval.args[0].value <= 0
        ):
            self._unsupported(
                "TRINO_INTERVAL_BUCKET_UNSUPPORTED",
                "toStartOfInterval supports positive constant second and minute intervals in Trino mode.",
                node,
            )
        seconds = unit * interval.args[0].value
        value = self.visit(node.args[0])
        return (
            f"date_add('second', CAST(floor(date_diff('second', TIMESTAMP '1970-01-01 00:00:00', "
            f"{value}) / {seconds}e0) AS BIGINT) * {seconds}, TIMESTAMP '1970-01-01 00:00:00')"
        )

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
        key_expression = node.args[0]
        if isinstance(key_expression, ast.Array) and all(
            isinstance(key, ast.Constant) and key.value is not None for key in key_expression.exprs
        ):
            key_values = [key.value for key in key_expression.exprs if isinstance(key, ast.Constant)]
            if any(value in key_values[:index] for index, value in enumerate(key_values)):
                self._unsupported(
                    "TRINO_MAP_DUPLICATE_KEYS_UNSUPPORTED",
                    "ClickHouse maps with duplicate keys cannot be represented safely in Trino.",
                    node,
                )
            return self._visit_binary_function(node, "map")
        keys = self.visit(node.args[0])
        values = self.visit(node.args[1])
        unique_keys = f"filter(array_distinct({keys}), __hogql_key -> __hogql_key IS NOT NULL)"
        aligned_values = (
            f"transform({unique_keys}, __hogql_key -> element_at({values}, array_position({keys}, __hogql_key)))"
        )
        return f"map({unique_keys}, {aligned_values})"

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

    def _visit_round_bankers(self, node: ast.Call) -> str:
        if len(node.args) not in {1, 2}:
            self._invalid_function_arguments(node, "roundBankers expects a value and optional constant precision.")
        precision = node.args[1] if len(node.args) == 2 else ast.Constant(value=0)
        if (
            not isinstance(precision, ast.Constant)
            or type(precision.value) is not int
            or not -18 <= precision.value <= 18
        ):
            self._unsupported(
                "TRINO_ROUND_BANKERS_PRECISION_UNSUPPORTED",
                "roundBankers requires a constant precision between -18 and 18.",
                node,
            )
        digits = precision.value
        step = "0." + "0" * (digits - 1) + "1" if digits > 0 else "1" + "0" * -digits
        half = "0." + "0" * digits + "5" if digits >= 0 else "5" + "0" * (-digits - 1)
        source = self.visit(node.args[0])
        value = "__hogql_round_value"
        rounded = f"round({value}, {digits})"
        return (
            f"element_at(transform(ARRAY[{source}], {value} -> "
            f"CASE WHEN abs({value} - {rounded}) = DECIMAL '{half}' "
            f"AND mod({rounded}, DECIMAL '{step}' * 2) <> 0 "
            f"THEN {rounded} - sign({value}) * DECIMAL '{step}' ELSE {rounded} END), 1)"
        )

    def _visit_constant_regex(self, node: ast.Call) -> str:
        replacing = node.name.lower() == "replaceregexpone"
        if len(node.args) != (3 if replacing else 2):
            self._invalid_function_arguments(node, f"{node.name} has an invalid argument count.")
        pattern = node.args[1]
        if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
            self._unsupported("TRINO_REGEX_CONSTANT_REQUIRED", f"{node.name} requires a constant pattern.", node)
        if "(?P" in pattern.value:
            self._unsupported(
                "TRINO_REGEX_PATTERN_UNSUPPORTED", "Named Python regex groups are not supported in Trino mode.", node
            )
        try:
            groups = re.compile(pattern.value).groups
        except re.error:
            self._unsupported(
                "TRINO_REGEX_PATTERN_UNSUPPORTED", "The regular expression cannot be analyzed statically.", node
            )
        value = self.visit(node.args[0])
        if not replacing:
            if groups < 1 or groups > 5:
                self._unsupported(
                    "TRINO_REGEX_GROUPS_UNSUPPORTED", "extractAllGroups requires between 1 and 5 capture groups.", node
                )
            regex = self.context.add_value("(?s)" + pattern.value)
            columns = [f"regexp_extract_all({value}, {regex}, {i})" for i in range(1, groups + 1)]
            if groups == 1:
                return f"transform({columns[0]}, __hogql_group -> ARRAY[coalesce(__hogql_group, '')])"
            entries = ", ".join(f"coalesce(__hogql_match[{i}], '')" for i in range(1, groups + 1))
            return f"transform(zip({', '.join(columns)}), __hogql_match -> ARRAY[{entries}])"
        replacement = node.args[2]
        if not isinstance(replacement, ast.Constant) or not isinstance(replacement.value, str):
            self._unsupported(
                "TRINO_REGEX_CONSTANT_REQUIRED", "replaceRegexpOne requires a constant replacement.", node
            )
        if "(?" in pattern.value or re.search(r"\\[1-9]", pattern.value):
            self._unsupported(
                "TRINO_REGEX_PATTERN_UNSUPPORTED",
                "replaceRegexpOne requires a pattern without lookarounds, inline flags, or backreferences.",
                node,
            )
        parts = ["__hogql_match[1]"]
        index = 0
        while index < len(replacement.value):
            char = replacement.value[index]
            if char == "\\" and index + 1 < len(replacement.value):
                index += 1
                char = replacement.value[index]
                if char in "0123456789":
                    if int(char) > groups:
                        self._invalid_function_arguments(node, "Replacement refers to a missing capture group.")
                    parts.append(f"coalesce(__hogql_match[{int(char) + 2}], '')")
                    index += 1
                    continue
            parts.append(self.context.add_value(char))
            index += 1
        parts.append(f"__hogql_match[{groups + 3}]")
        regex = self.context.add_value(r"(?s)\A(.*?)(" + pattern.value + r")(.*)\z")
        substitute = " || ".join(parts)
        return f"regexp_replace({value}, {regex}, __hogql_match -> {substitute})"

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

    def visit_array_access(self, node: ast.ArrayAccess) -> str:
        root: ast.Expr = node.array
        while isinstance(root, ast.ArrayAccess):
            root = root.array
        if isinstance(self._resolve_type(root), ast.StringType) and isinstance(
            self._resolve_type(node.property), ast.StringType
        ):
            parent = self.stack[-2] if len(self.stack) > 1 else None
            function = (
                "json_extract"
                if isinstance(parent, ast.ArrayAccess) and parent.array is node
                else "json_extract_scalar"
            )
            return f"{function}({self.visit(node.array)}, {self._json_path([self._constant_string(node.property)])})"
        return f"element_at({self.visit(node.array)}, {self.visit(node.property)})"

    def _constant_string(self, node: ast.Expr) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        self._unsupported(
            "TRINO_JSON_DYNAMIC_PATH_UNSUPPORTED",
            "String-backed bracket access requires a constant key in Trino mode.",
            node,
        )

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
        if name in {"quantile", "quantileexact", "quantileif", "quantileexactif"}:
            filtered = name.endswith("if")
            expected_args = 2 if filtered else 1
            if node.args is None or len(node.args) != expected_args or node.exprs is None or len(node.exprs) != 1:
                self._unsupported(
                    "TRINO_WINDOW_FUNCTION_ARGUMENTS_UNSUPPORTED",
                    f"Window function '{node.name}' has unsupported arguments in Trino mode.",
                    node,
                )
            call = f"approx_percentile({self.visit(node.args[0])}, {self.visit(node.exprs[0])})"
            if filtered:
                call += f" FILTER (WHERE {self.visit(node.args[1])})"
        elif node.args:
            self._unsupported(
                "TRINO_WINDOW_FUNCTION_PARAMETERS_UNSUPPORTED",
                f"Parametric window function '{node.name}' is not supported in Trino mode.",
                node,
            )
        elif name == "laginframe":
            self._unsupported(
                "TRINO_LAG_IN_FRAME_UNSUPPORTED",
                "lagInFrame has no semantics-safe native Trino equivalent.",
                node,
            )
        exprs = [self.visit(expr) for expr in node.exprs or []]
        if name in {"quantile", "quantileexact", "quantileif", "quantileexactif"}:
            pass
        elif name in _TRINO_CONDITIONAL_WINDOW_FUNCTIONS:
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
