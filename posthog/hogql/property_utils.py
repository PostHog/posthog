from typing import Any, Union

from posthog.hogql import ast


def create_property_condition(property_key: str, value: Any) -> ast.CompareOperation:
    """Creates a HogQL AST CompareOperation node for comparing a property value.

    Args:
        property_key: The key of the property to compare
        value: The value to compare against (will be converted to string and lowercased for consistent comparison)

    Returns:
        An AST CompareOperation node that compares the property value
    """
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Call(name="toString", args=[ast.Field(chain=["properties", property_key])]),
        right=ast.Constant(value=str(value).lower()),
    )


def create_property_conditions(property_key: str, property_values: Union[list, Any]) -> ast.Expr:
    """Creates HogQL AST nodes for comparing property values, handling both single values and lists.

    Args:
        property_key: The key of the property to compare
        property_values: Either a single value or a list of values to compare against

    Returns:
        If property_values is a list with multiple items: An OR condition combining all value comparisons
        If property_values is a list with one item or a single value: A single comparison operation
    """
    if isinstance(property_values, list):
        value_conditions: list[ast.Expr] = [create_property_condition(property_key, value) for value in property_values]
        return ast.Or(exprs=value_conditions) if len(value_conditions) > 1 else value_conditions[0]
    else:
        return create_property_condition(property_key, property_values)
