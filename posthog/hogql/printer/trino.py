from collections.abc import Callable
from typing import ClassVar, NoReturn, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.trino_locator import resolve_trino_table_locator
from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import clone_expr

_TRINO_WINDOW_FUNCTIONS = frozenset(
    {
        "avg",
        "count",
        "cume_dist",
        "dense_rank",
        "first_value",
        "lag",
        "last_value",
        "lead",
        "max",
        "min",
        "nth_value",
        "ntile",
        "percent_rank",
        "rank",
        "row_number",
        "sum",
    }
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

    def _unsupported(self, feature_code: str, detail: str, node: ast.Expr | None = None) -> NoReturn:
        construct = node.name if isinstance(node, ast.Call) else node.__class__.__name__ if node else detail
        raise TrinoLoweringError(feature_code, construct, node, detail=detail)

    def _invalid_function_arguments(self, node: ast.Call, detail: str) -> NoReturn:
        self._unsupported("TRINO_FUNCTION_ARGUMENTS_UNSUPPORTED", detail, node)

    def visit_call(self, node: ast.Call) -> str:
        name = node.name.lower()
        if name in {"empty", "notempty"}:
            return self._visit_empty(node, negated=name == "notempty")
        if name == "concat":
            if node.distinct or node.order_by:
                self._unsupported(
                    "TRINO_CONCAT_MODIFIER_UNSUPPORTED",
                    "concat does not support DISTINCT or ORDER BY in Trino mode.",
                    node,
                )
            args = [self.visit(arg) for arg in node.args]
            rendered = [
                f"CAST({value} AS VARCHAR)" if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else value
                for arg, value in zip(node.args, args, strict=True)
            ]
            return f"concat({', '.join(rendered)})"
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
            left, right = self._visit_binary_args(node)
            return f"(cardinality(array_intersect({left}, {right})) > 0)"
        if name == "hasall":
            left, right = self._visit_binary_args(node)
            return f"(cardinality(array_except({right}, {left})) = 0)"
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
            left, right = self._visit_binary_args(node)
            return f"split({right}, {left})"
        if name == "md5":
            value = self._visit_unary_arg(node)
            return f"lower(to_hex(md5(to_utf8(CAST({value} AS VARCHAR)))))"
        if name == "extract":
            return self._visit_extract(node)
        if name in {"quantile", "quantileif"}:
            return self._visit_quantile(node, filtered=name == "quantileif")
        if name == "json_value":
            return self._visit_json_value(node)
        return super().visit_call(node)

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
        target_types = {
            "String": "VARCHAR",
            "Int64": "BIGINT",
            "UInt64": "DECIMAL(20, 0)",
            "Float64": "DOUBLE",
            "Bool": "BOOLEAN",
            "Array(String)": "ARRAY(VARCHAR)",
        }
        target = target_types.get(type_arg.value)
        if target is None:
            self._unsupported(
                "TRINO_JSON_TARGET_TYPE_UNSUPPORTED",
                f"JSONExtract target type '{type_arg.value}' is not supported in Trino mode.",
                node,
            )
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
        extractor = "json_extract" if target.startswith("ARRAY") else "json_extract_scalar"
        return f"CAST({extractor}({source}, {path}) AS {target})"

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
        if name == "jsonhas":
            return f"(json_extract({source}, {path}) IS NOT NULL)"
        if name == "jsonlength":
            return f"json_size({source}, {path})"
        return f"map_keys(CAST(json_extract({source}, {path}) AS MAP(VARCHAR, JSON)))"

    def _visit_to_json_string(self, node: ast.Call) -> str:
        value = self._visit_unary_arg(node)
        return f"json_format(CAST({value} AS JSON))"

    def _visit_empty(self, node: ast.Call, *, negated: bool) -> str:
        if len(node.args) != 1:
            self._invalid_function_arguments(node, f"{node.name} expects exactly 1 argument in Trino mode.")
        arg = node.args[0]
        rendered = self.visit(arg)
        arg_type = resolve_field_type(arg)
        value_expr = arg
        while isinstance(value_expr, ast.Alias):
            value_expr = value_expr.expr
        if isinstance(value_expr, ast.PropertyAccess):
            arg_type = ast.StringType(nullable=True)
        if isinstance(arg_type, (ast.ArrayType, ast.MapType)):
            comparison = "> 0" if negated else "= 0"
            return f"({rendered} IS {'NOT ' if negated else ''}NULL AND cardinality({rendered}) {comparison})"
        if isinstance(arg_type, ast.StringType):
            comparison = "<> ''" if negated else "= ''"
            return f"({rendered} IS {'NOT ' if negated else ''}NULL AND {rendered} {comparison})"
        self._unsupported(
            "TRINO_EMPTY_ARGUMENT_TYPE_UNSUPPORTED",
            f"{node.name} requires a string, array, or map argument in Trino mode.",
            node,
        )

    def _json_path(self, members: list[str | int]) -> str:
        path = "$"
        for member in members:
            if isinstance(member, int):
                path += f"[{member}]"
            else:
                escaped = str(member).replace("\\", "\\\\").replace('"', '\\"')
                path += f'."{escaped}"'
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

    def _visit_binary_args(self, node: ast.Call) -> tuple[str, str]:
        if len(node.args) != 2:
            self._invalid_function_arguments(node, f"{node.name} expects exactly 2 arguments in Trino mode.")
        return self.visit(node.args[0]), self.visit(node.args[1])

    def _visit_binary_function(self, node: ast.Call, target: str) -> str:
        left, right = self._visit_binary_args(node)
        return f"{target}({left}, {right})"

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
        return f"count(DISTINCT {', '.join(self.visit(arg) for arg in node.args)})"

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
        path_literal = "'" + path.value.replace("'", "''") + "'"
        return f"json_value({self.visit(node.args[0])}, {path_literal})"

    def _print_table_sql(self, table) -> str:
        return self._print_table(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectTrinoTable):
            return table.to_printed_trino(self.context)
        if hasattr(table, "to_printed_trino"):
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
        if name not in _TRINO_WINDOW_FUNCTIONS:
            self._unsupported(
                "TRINO_WINDOW_FUNCTION_UNSUPPORTED",
                f"Window function '{node.name}' is not supported in Trino mode.",
                node,
            )
        exprs = [self.visit(expr) for expr in node.exprs or []]
        cloned_node = cast(ast.WindowFunction, clone_expr(node))
        identifier = self._apply_window_function_rewrites(name, exprs, cloned_node)
        args = f"({', '.join(self.visit(arg) for arg in cloned_node.args)})" if cloned_node.args else ""
        if cloned_node.over_expr:
            over = f"({self.visit(cloned_node.over_expr)})"
        elif cloned_node.over_identifier:
            over = self._print_identifier(cloned_node.over_identifier)
        else:
            over = "()"
        if cloned_node.args:
            return f"{identifier}({', '.join(exprs)}){args} OVER {over}"
        return f"{identifier}({', '.join(exprs)}) OVER {over}"

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
        if node.start_expr is None or node.end_expr is None:
            self._unsupported(
                "TRINO_OPEN_ARRAY_SLICE_UNSUPPORTED",
                "Open-ended array slices are not supported in Trino mode.",
                node,
            )
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
            self._unsupported("TRINO_CAST_TYPE_UNSUPPORTED", f"Type '{type_name}' is not supported in Trino mode.")
        return target

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        if not unsafe_args:
            return unsafe_field
        if len(unsafe_args) != 1:
            self._unsupported(
                "TRINO_JSON_PROPERTY_NOT_LOWERED",
                "Nested JSON property access must be lowered before Trino printing.",
            )
        return f"json_extract_scalar({unsafe_field}, {unsafe_args[0]})"

    def _json_property_args(self, chain) -> list[str]:
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
