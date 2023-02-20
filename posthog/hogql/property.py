from typing import Any, Tuple, Union, cast

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.constants import HOGQL_AGGREGATIONS
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor
from posthog.models import Action, Property
from posthog.models.property import PropertyGroup
from posthog.schema import PropertyOperator


def has_aggregation(expr: ast.AST) -> bool:
    finder = AggregationFinder()
    finder.visit(expr)
    return finder.has_aggregation


class AggregationFinder(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.has_aggregation = False

    def visit(self, node):
        if self.has_aggregation:
            return
        else:
            super().visit(node)

    def visit_call(self, node: ast.Call):
        if node.name in HOGQL_AGGREGATIONS:
            self.has_aggregation = True
        else:
            for arg in node.args:
                self.visit(arg)


def action_to_expr(action: Action) -> ast.Expr:
    raise NotImplementedError("action_to_expr not implemented")


def property_to_expr(property: Union[BaseModel, PropertyGroup, Property, dict]) -> ast.Expr:
    if isinstance(property, dict):
        property = Property(**property)
    elif isinstance(property, Property):
        pass
    elif isinstance(property, PropertyGroup):
        raise NotImplementedError("PropertyGroup not implemented")
    elif isinstance(property, BaseModel):
        property = Property(**property.dict())
    else:
        raise NotImplementedError(f"property_to_expr with property of type {type(property).__name__} not implemented")

    if property.type == "event" or cast(Any, property.type) == "feature":
        op, value = property_operator_to_compare_operator_type(
            cast(PropertyOperator, property.operator or PropertyOperator.exact), property.value
        )
        return ast.CompareOperation(
            op=op,
            left=ast.Field(chain=["properties", property.key]),
            right=ast.Constant(value=value),
        )
    elif property.type == "person":
        op, value = property_operator_to_compare_operator_type(
            cast(PropertyOperator, property.operator or PropertyOperator.exact), property.value
        )
        return ast.CompareOperation(
            op=op,
            left=ast.Field(chain=["person", "properties", property.key]),
            right=ast.Constant(value=value),
        )
    elif property.type == "hogql":
        return parse_expr(property.key)

    # "cohort",
    # "element",
    # "static-cohort",
    # "precalculated-cohort",
    # "group",
    # "recording",
    # "behavioral",
    # "session",

    raise NotImplementedError(f"property_to_expr not implemented for filter type {type(property).__name__}")


def property_operator_to_compare_operator_type(
    operator: PropertyOperator, value: Any
) -> Tuple[ast.CompareOperationType, Any]:
    if isinstance(value, list):
        if len(value) == 1:
            value = value[0]
        else:
            raise NotImplementedError(
                "property_operator_to_compare_operator_type not implemented for list of length > 1"
            )
    if operator == PropertyOperator.exact or operator == PropertyOperator.is_set:
        return ast.CompareOperationType.Eq, value
    elif operator == PropertyOperator.is_not or operator == PropertyOperator.is_not_set:
        return ast.CompareOperationType.NotEq, value
    elif operator == PropertyOperator.lt:
        return ast.CompareOperationType.Lt, value
    elif operator == PropertyOperator.gt:
        return ast.CompareOperationType.Gt, value
    elif operator == PropertyOperator.lte:
        return ast.CompareOperationType.LtE, value
    elif operator == PropertyOperator.gte:
        return ast.CompareOperationType.GtE, value
    elif operator == PropertyOperator.icontains:
        return ast.CompareOperationType.ILike, f"%{value}%"
    elif operator == PropertyOperator.not_icontains:
        return ast.CompareOperationType.NotILike, f"%{value}%"

    #     regex = "regex"
    #     not_regex = "not_regex"
    #     is_date_exact = "is_date_exact"
    #     is_date_before = "is_date_before"
    #     is_date_after = "is_date_after"
    #     between = "between"
    #     not_between = "not_between"
    #     min = "min"
    #     max = "max"

    raise NotImplementedError(f"PropertyOperator f{operator} not implemented")
