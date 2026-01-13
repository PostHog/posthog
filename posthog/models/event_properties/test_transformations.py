"""
Tests to ensure transformations.py stays in sync with HogQL's type conversion logic.

These transformations are used by the MV and backfill to convert JSON property values
to typed columns. They MUST produce identical SQL to what HogQL generates when it
wraps property accesses with type conversion functions (toFloat, toBool, etc).
"""

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import ClickHousePrinter
from posthog.hogql.transforms.property_types import PropertySwapper

from posthog.models.event_properties.transformations import boolean_transform, numeric_transform


def get_hogql_type_conversion_sql(field_type: str, placeholder: str) -> str:
    """
    Get the SQL that HogQL generates for a type conversion.

    Uses PropertySwapper._field_type_to_property_call to generate the AST,
    then prints it to ClickHouse SQL and substitutes params back in.
    """
    # Create a minimal PropertySwapper just to call _field_type_to_property_call
    swapper = PropertySwapper(
        timezone="UTC",
        event_properties={},
        person_properties={},
        group_properties={},
        context=HogQLContext(team_id=1, enable_select_queries=True),
        setTimeZones=False,
    )

    # Create placeholder node and get the type conversion AST
    placeholder_node = ast.Constant(value=placeholder)
    converted_ast = swapper._field_type_to_property_call(placeholder_node, field_type)

    # Print to ClickHouse SQL
    context = HogQLContext(team_id=1, enable_select_queries=True)
    printer = ClickHousePrinter(context=context, dialect="clickhouse", stack=[], settings=None, pretty=False)
    sql = printer.visit(converted_ast)

    # Substitute params back in for comparison
    for key, value in context.values.items():
        param_placeholder = f"%({key})s"
        if isinstance(value, str):
            sql = sql.replace(param_placeholder, f"'{value}'")
        elif isinstance(value, list):
            list_str = "[" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in value) + "]"
            sql = sql.replace(param_placeholder, list_str)
        elif value is None:
            sql = sql.replace(param_placeholder, "NULL")
        else:
            sql = sql.replace(param_placeholder, str(value))

    return sql


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
            ("numeric", "Float", numeric_transform),
            ("boolean", "Boolean", boolean_transform),
        ]
    )
    def test_transformation_matches_hogql(self, name: str, field_type: str, transform_func):
        hogql_sql = get_hogql_type_conversion_sql(field_type, PLACEHOLDER)
        transformation_sql = transform_func(f"'{PLACEHOLDER}'")

        assert hogql_sql == transformation_sql, (
            f"Transformation '{name}' drifted from HogQL!\n"
            f"  HogQL _field_type_to_property_call produces: {hogql_sql}\n"
            f"  transformations.{transform_func.__name__} produces: {transformation_sql}\n"
            f"\n"
            f"These must match to ensure MV/backfill data matches query-time conversions."
        )
