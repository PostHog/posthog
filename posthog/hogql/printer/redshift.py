from collections.abc import Callable
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.errors import QueryError
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.redshift_functions import (
    REDSHIFT_FUNCTION_HANDLERS_LOWER,
    REDSHIFT_FUNCTION_RENAMES_LOWER,
    REDSHIFT_PASSTHROUGH_FUNCTIONS,
)


class RedshiftPrinter(PostgresPrinter):
    """Prints a HogQL AST as Amazon Redshift SQL.

    Redshift is a fork of an old Postgres, so almost the entire ``PostgresPrinter`` surface —
    identifiers, operators (ILIKE, POSIX ``~``), date_trunc/extract, CAST, CTEs, window functions —
    is emitted unchanged. This subclass is mostly **subtractive**: it blocks the constructs the
    Redshift engine can't run, raising a clear ``QueryError`` rather than shipping SQL that would
    fail server-side. The exceptions are a few semantic-preserving rewrites where Redshift would
    otherwise silently return different results than HogQL promises: integer division is cast to
    float (Redshift ``/`` truncates), and ``avg``/``concat``/``position`` are re-rendered in
    ``redshift_functions._REDSHIFT_ONLY_HANDLERS``.

    Redshift *does* support (so they stay inherited): FULL OUTER JOIN, QUALIFY, recursive CTEs,
    ILIKE, and the POSIX regex operators. The blocked set below is what it does *not* support.
    """

    DIALECT_NAME: ClassVar[HogQLDialect] = "redshift"
    DIALECT_LABEL: ClassVar[str] = "Redshift"

    def _dialect_error_suffix(self) -> str:
        return "in the Redshift dialect"

    # --- function sets (Postgres minus the Redshift-incompatible entries) --------------

    def _get_function_renames(self) -> dict[str, str]:
        return REDSHIFT_FUNCTION_RENAMES_LOWER

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return REDSHIFT_FUNCTION_HANDLERS_LOWER

    def _get_passthrough_functions(self) -> frozenset[str]:
        return REDSHIFT_PASSTHROUGH_FUNCTIONS

    # --- semantic-preserving rewrites ---------------------------------------------------

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> str:
        if node.op == ast.ArithmeticOperationOp.Div:
            # Redshift `/` on two integers truncates; HogQL division is always float.
            return f"(CAST({self.visit(node.left)} AS DOUBLE PRECISION) / {self.visit(node.right)})"
        return super().visit_arithmetic_operation(node)

    # --- blocked constructs (no Redshift equivalent) -----------------------------------

    def visit_array(self, node: ast.Array):
        raise QueryError("Arrays are not supported in the Redshift dialect")

    def visit_array_slice(self, node: ast.ArraySlice):
        raise QueryError("Array slicing is not supported in the Redshift dialect")

    def visit_lambda(self, node: ast.Lambda):
        raise QueryError("Lambdas are not supported in the Redshift dialect")

    def visit_dict(self, node: ast.Dict):
        raise QueryError("Dicts are not supported in the Redshift dialect")

    def visit_try_cast(self, node: ast.TryCast):
        raise QueryError("TRY_CAST is not supported in the Redshift dialect")

    def visit_tuple(self, node: ast.Tuple) -> str:
        # Redshift has no ROW() row constructor. A multi-value tuple is still valid as an
        # `IN (...)` value list / parenthesized grouping, but a single-element tuple can only be a
        # 1-column row constructor, which Redshift can't express.
        values = [self.visit(expr) for expr in node.exprs]
        if len(values) == 1:
            raise QueryError("Single-element tuples are not supported in the Redshift dialect")
        return f"({', '.join(values)})"

    def _render_start_of(self, unit: str, arg: str, week_mode: int = 3) -> str:
        # The Postgres isoyear expansion uses make_date() + extract(isoyear ...), neither of which
        # Redshift supports. Every other unit expands to date_trunc()/interval arithmetic, which
        # Redshift runs unchanged.
        if unit == "isoyear":
            raise QueryError("toStartOfISOYear is not supported in the Redshift dialect")
        return super()._render_start_of(unit, arg, week_mode=week_mode)

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        # Postgres renders blob property reads with the `->`/`->>` JSON operators, which Redshift
        # does not have. Block the implicit path; explicit json_extract_path_text(...) via the
        # JSONExtractString rename is still available for users who need JSON access.
        raise QueryError("JSON property access (-> / ->>) is not supported in the Redshift dialect")
