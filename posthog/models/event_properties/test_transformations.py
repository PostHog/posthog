"""
Tests to ensure transformations.py stays in sync with HogQL's type conversion logic.

These transformations are used by the MV and backfill to convert JSON property values
to typed columns. They MUST produce identical SQL to what HogQL generates when it
wraps property accesses with type conversion functions (toFloat, toBool, etc).
"""

import pytest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import ClickHousePrinter

from posthog.models.event_properties.transformations import boolean_transform, numeric_transform


def print_expr_to_clickhouse(expr: ast.Expr) -> tuple[str, HogQLContext]:
    """Print an AST expression to ClickHouse SQL, returning sql and context."""
    context = HogQLContext(team_id=1, enable_select_queries=True)
    printer = ClickHousePrinter(context=context, dialect="clickhouse", stack=[], settings=None, pretty=False)
    sql = printer.visit(expr)
    return sql, context


def substitute_params(sql: str, context: HogQLContext) -> str:
    """Substitute parameterized values back into SQL for comparison."""
    result = sql
    for key, value in context.values.items():
        placeholder = f"%({key})s"
        if isinstance(value, str):
            result = result.replace(placeholder, f"'{value}'")
        elif isinstance(value, list):
            list_str = "[" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in value) + "]"
            result = result.replace(placeholder, list_str)
        elif value is None:
            result = result.replace(placeholder, "NULL")
        else:
            result = result.replace(placeholder, str(value))
    return result


# Placeholder used to compare transformation output
PLACEHOLDER = "__TEST_VALUE__"


class TestTransformationsMatchHogQL:
    """
    Verify that transformations.py produces the same SQL as HogQL's _field_type_to_property_call.

    This prevents drift between:
    - The MV/backfill SQL (which uses transformations.py)
    - HogQL query-time type conversions (which use ast.Call nodes printed via conversions.py)
    """

    @parameterized.expand(
        [
            ("numeric", "Float"),
            ("boolean", "Boolean"),
        ]
    )
    def test_transformation_matches_hogql(self, transform_name: str, field_type: str):
        """
        Test that transformation function output matches HogQL's _field_type_to_property_call.

        This mirrors the logic in property_types.py:_field_type_to_property_call
        """
        # Build AST the same way _field_type_to_property_call does
        placeholder_node = ast.Constant(value=PLACEHOLDER)

        if field_type == "Float":
            hogql_ast = ast.Call(name="toFloat", args=[placeholder_node])
            transformation_sql = numeric_transform(f"'{PLACEHOLDER}'")
        elif field_type == "Boolean":
            hogql_ast = ast.Call(
                name="toBool",
                args=[
                    ast.Call(
                        name="transform",
                        args=[
                            ast.Call(name="toString", args=[placeholder_node]),
                            ast.Constant(value=["true", "false"]),
                            ast.Constant(value=[1, 0]),
                            ast.Constant(value=None),
                        ],
                    )
                ],
            )
            transformation_sql = boolean_transform(f"'{PLACEHOLDER}'")
        else:
            pytest.fail(f"Unknown field type: {field_type}")

        hogql_sql, context = print_expr_to_clickhouse(hogql_ast)
        hogql_sql_substituted = substitute_params(hogql_sql, context)

        assert hogql_sql_substituted == transformation_sql, (
            f"Transformation '{transform_name}' drifted from HogQL!\n"
            f"  HogQL produces:         {hogql_sql_substituted}\n"
            f"  transformations.py has: {transformation_sql}\n"
            f"\n"
            f"These must match to ensure MV/backfill data matches query-time conversions."
        )
