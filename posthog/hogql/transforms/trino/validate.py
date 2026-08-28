from typing import NoReturn

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.trino_locator import resolve_trino_table_locator
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import TraversingVisitor

_SPECIAL_CALLS = frozenset(
    {
        "percentile_cont",
        "percentile_disc",
        "argmax",
        "argmaxif",
        "argmin",
        "argminif",
        "arrayconcat",
        "arraydistinct",
        "arrayelement",
        "arrayfilter",
        "arrayfirst",
        "arrayflatten",
        "arraymap",
        "arraymin",
        "arraysort",
        "arraysum",
        "empty",
        "extract",
        "extractall",
        "grouparrayif",
        "groupuniqarrayif",
        "groupuniqarray",
        "has",
        "hasall",
        "hasany",
        "countdistinct",
        "jsonextract",
        "jsonextractarrayraw",
        "jsonextractbool",
        "jsonextractfloat",
        "jsonextractint",
        "jsonextractkeys",
        "jsonextractkeysandvaluesraw",
        "jsonextractraw",
        "jsonextractstring",
        "jsonextractuint",
        "jsonhas",
        "jsonlength",
        "match",
        "md5",
        "notempty",
        "quantile",
        "quantileif",
        "range",
        "splitbychar",
        "splitbystring",
        "todecimal",
        "tojsonstring",
        "tuple",
        "tupleelement",
        "tostartofday",
        "tostartoffifteenminutes",
        "tostartoffiveminutes",
        "tostartofhour",
        "tostartofisoyear",
        "tostartofminute",
        "tostartofmonth",
        "tostartofquarter",
        "tostartofsecond",
        "tostartoftenminutes",
        "tostartofweek",
        "tostartofyear",
    }
)
_SEMANTIC_CALLS = frozenset({"cohort", "matchesaction", "savedquery"})
_SUPPORTED_CALLS = frozenset(
    {
        *TRINO_FUNCTION_HANDLERS_LOWER,
        *TRINO_FUNCTION_RENAMES_LOWER,
        *TRINO_PASSTHROUGH_FUNCTIONS,
        *_SPECIAL_CALLS,
    }
)


class TrinoReadyValidator(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def _fail(self, feature_code: str, construct: str, node: ast.Expr | None = None) -> NoReturn:
        raise TrinoLoweringError(feature_code, construct, node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.array_join_op is not None or node.array_join_list:
            self._fail("TRINO_ARRAY_JOIN_NOT_LOWERED", "ARRAY JOIN", node)
        if node.limit_by is not None:
            self._fail("TRINO_LIMIT_BY_NOT_LOWERED", "LIMIT BY", node)
        if node.qualify is not None:
            self._fail("TRINO_QUALIFY_NOT_LOWERED", "QUALIFY", node)
        if node.prewhere is not None:
            self._fail("TRINO_PREWHERE_NOT_LOWERED", "PREWHERE", node)
        if node.interpolate is not None:
            self._fail("TRINO_INTERPOLATE_UNSUPPORTED", "INTERPOLATE", node)
        if node.limit_percent:
            self._fail("TRINO_LIMIT_PERCENT_UNSUPPORTED", "LIMIT PERCENT", node)
        if node.limit_with_ties:
            self._fail("TRINO_WITH_TIES_NOT_LOWERED", "WITH TIES", node)
        super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        join_type = node.join_type or ""
        if "ANY" in join_type.split():
            self._fail("TRINO_ANY_JOIN_NOT_LOWERED", join_type, node)
        if "ASOF" in join_type.split():
            self._fail("TRINO_ASOF_JOIN_UNSUPPORTED", join_type, node)
        if join_type.startswith("GLOBAL "):
            self._fail("TRINO_GLOBAL_JOIN_UNSUPPORTED", join_type, node)
        if node.table_final:
            self._fail("TRINO_FINAL_UNSUPPORTED", "FINAL", node)
        if node.sample is not None:
            self._fail("TRINO_SAMPLE_UNSUPPORTED", "SAMPLE", node)
        super().visit_join_expr(node)

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        if name in _SEMANTIC_CALLS:
            self._fail("TRINO_SEMANTIC_CALL_NOT_RESOLVED", node.name, node)
        if name == "arrayjoin":
            self._fail("TRINO_ARRAY_JOIN_FUNCTION_NOT_LOWERED", node.name, node)
        if name not in _SUPPORTED_CALLS:
            self._fail("TRINO_FUNCTION_UNSUPPORTED", node.name, node)
        super().visit_call(node)

    def visit_lazy_table_type(self, node: ast.LazyTableType) -> None:
        self._fail("TRINO_LAZY_TABLE_NOT_RESOLVED", node.table.name or node.table.__class__.__name__)

    def visit_lazy_join_type(self, node: ast.LazyJoinType) -> None:
        self._fail("TRINO_LAZY_JOIN_NOT_RESOLVED", node.table.name or node.table.__class__.__name__)

    def visit_virtual_table_type(self, node: ast.VirtualTableType) -> None:
        self._fail("TRINO_VIRTUAL_TABLE_NOT_RESOLVED", "virtual relationship")

    def visit_property_type(self, node: ast.PropertyType) -> None:
        self._fail("TRINO_PROPERTY_NOT_LOWERED", "logical property access")

    def visit_map_property_type(self, node: ast.PropertyType) -> None:
        self._fail("TRINO_PROPERTY_NOT_LOWERED", "logical map property access")

    def visit_table_type(self, node: ast.TableType) -> None:
        if (
            not hasattr(node.table, "to_printed_trino")
            and resolve_trino_table_locator(node.table, self.context) is None
        ):
            self._fail(
                "TRINO_TABLE_LOCATOR_MISSING",
                f"table {node.table.name or node.table.__class__.__name__}",
            )


def validate_trino_ready_ast(node: ast.AST, context: HogQLContext) -> None:
    TrinoReadyValidator(context).visit(node)
