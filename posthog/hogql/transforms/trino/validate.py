from typing import NoReturn

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.trino_locator import resolve_trino_table_locator
from posthog.hogql.printer.trino_functions import (
    TRINO_FUNCTION_HANDLERS_LOWER,
    TRINO_FUNCTION_RENAMES_LOWER,
    TRINO_PASSTHROUGH_FUNCTIONS,
)
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.persons import is_internal_trino_logical_table
from posthog.hogql.visitor import TraversingVisitor

from posthog.schema_enums import PersonsOnEventsMode

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
        "in",
        "countdistinct",
        "date_part",
        "dateadd",
        "datesub",
        "jsonextract",
        "jsonextractarrayraw",
        "jsonextractbool",
        "jsonextractfloat",
        "jsonextractint",
        "jsonextractkeys",
        "jsonextractkeysandvalues",
        "jsonextractkeysandvaluesraw",
        "jsonextractraw",
        "jsonextractstring",
        "jsonextractuint",
        "jsonhas",
        "jsonlength",
        "match",
        "md5",
        "notempty",
        "notin",
        "parsedatetime",
        "quantile",
        "quantileif",
        "range",
        "repeat",
        "splitbychar",
        "splitbystring",
        "todecimal",
        "todatetime64",
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
        "tolastdayofweek",
        "totimezone",
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


def validate_trino_context(context: HogQLContext) -> None:
    mode = context.modifiers.personsOnEventsMode
    if mode != PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
        mode_name = mode.value if mode is not None else "unset"
        raise TrinoLoweringError(
            "TRINO_PERSONS_ON_EVENTS_MODE_UNSUPPORTED",
            f"personsOnEventsMode={mode_name}",
            detail=(
                "Trino compilation supports only "
                "personsOnEventsMode=person_id_override_properties_on_events. "
                f"The effective mode is {mode_name}. Change the query or project setting before compiling."
            ),
        )


class TrinoSourceValidator(TraversingVisitor):
    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field) and is_internal_trino_logical_table(node.table.chain):
            raise TrinoLoweringError("TRINO_INTERNAL_TABLE_UNAVAILABLE", "internal Trino table", node)
        super().visit_join_expr(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.settings is not None:
            raise TrinoLoweringError("TRINO_SETTINGS_UNSUPPORTED", "SETTINGS", node)
        super().visit_select_query(node)

    def visit_pivot_expr(self, node: ast.PivotExpr) -> None:
        raise TrinoLoweringError("TRINO_PIVOT_UNSUPPORTED", "PIVOT", node)

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> None:
        raise TrinoLoweringError("TRINO_UNPIVOT_UNSUPPORTED", "UNPIVOT", node)


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
        if node.limit_with_ties and (node.limit is None or not node.order_by):
            self._fail("TRINO_WITH_TIES_ORDER_REQUIRED", "WITH TIES without ORDER BY and LIMIT", node)
        if node.settings is not None:
            self._fail("TRINO_SETTINGS_UNSUPPORTED", "SETTINGS", node)
        super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        if node.limit_with_ties:
            self._fail("TRINO_SET_WITH_TIES_UNSUPPORTED", "WITH TIES on a set query", node)
        super().visit_select_set_query(node)

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
        if node.sample is not None and not (
            node.sample.sample_value.left.value == 1
            and node.sample.sample_value.right is None
            and node.sample.offset_value is None
        ):
            self._fail("TRINO_SAMPLE_UNSUPPORTED", "SAMPLE", node)
        super().visit_join_expr(node)

    def visit_order_expr(self, node: ast.OrderExpr) -> None:
        if node.with_fill is not None:
            self._fail("TRINO_WITH_FILL_UNSUPPORTED", "WITH FILL", node)
        super().visit_order_expr(node)

    def visit_cte(self, node: ast.CTE) -> None:
        if node.cte_type != "subquery":
            self._fail("TRINO_SCALAR_CTE_UNSUPPORTED", "scalar CTE", node)
        if node.materialized is not None or node.using_key is not None:
            self._fail("TRINO_CTE_MODIFIER_UNSUPPORTED", "CTE modifier", node)
        super().visit_cte(node)

    def visit_pivot_expr(self, node: ast.PivotExpr) -> None:
        self._fail("TRINO_PIVOT_UNSUPPORTED", "PIVOT", node)

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> None:
        self._fail("TRINO_UNPIVOT_UNSUPPORTED", "UNPIVOT", node)

    def visit_named_argument(self, node: ast.NamedArgument) -> None:
        self._fail("TRINO_NAMED_ARGUMENT_UNSUPPORTED", "named function argument", node)

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
        self._fail("TRINO_LAZY_JOIN_NOT_RESOLVED", f"lazy join {node.field}")

    def visit_virtual_table_type(self, node: ast.VirtualTableType) -> None:
        self._fail("TRINO_VIRTUAL_TABLE_NOT_RESOLVED", "virtual relationship")

    def visit_field(self, node: ast.Field) -> None:
        if (
            isinstance(node.type, ast.PropertyType)
            and node.type.joined_subquery is None
            and node.type.joined_subquery_field_name is None
        ):
            self._fail("TRINO_PROPERTY_NOT_LOWERED", "logical property access", node)
        super().visit_field(node)

    def visit_map_property_type(self, node: ast.PropertyType) -> None:
        self._fail("TRINO_PROPERTY_NOT_LOWERED", "logical map property access")

    def visit_table_type(self, node: ast.TableType) -> None:
        if (
            not isinstance(node.table, NumbersTable)
            and not hasattr(node.table, "to_printed_trino")
            and resolve_trino_table_locator(node.table, self.context) is None
        ):
            self._fail(
                "TRINO_TABLE_LOCATOR_MISSING",
                f"table {node.table.name or node.table.__class__.__name__}",
            )


def validate_trino_ready_ast(node: ast.AST, context: HogQLContext) -> None:
    TrinoReadyValidator(context).visit(node)


def validate_trino_source_ast(node: ast.AST) -> None:
    TrinoSourceValidator().visit(node)
