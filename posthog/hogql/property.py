import re
from typing import Any, List, Tuple, Union, cast

from pydantic import BaseModel

from posthog.constants import AUTOCAPTURE_EVENT, PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.constants import HOGQL_AGGREGATIONS
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor
from posthog.models import Action, ActionStep, Property
from posthog.models.event import Selector
from posthog.models.property import PropertyGroup
from posthog.models.property.util import build_selector_regex
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


def property_to_expr(property: Union[BaseModel, PropertyGroup, Property, dict, list]) -> ast.Expr:
    if isinstance(property, dict):
        property = Property(**property)
    elif isinstance(property, list):
        properties = [property_to_expr(p) for p in property]
        if len(properties) == 1:
            return properties[0]
        return ast.And(exprs=properties)
    elif isinstance(property, Property):
        pass
    elif isinstance(property, PropertyGroup):
        if property.type == PropertyOperatorType.AND:
            if len(property.values) == 1:
                return property_to_expr(property.values[0])
            return ast.And(exprs=[property_to_expr(p) for p in property.values])
        if property.type == PropertyOperatorType.OR:
            if len(property.values) == 1:
                return property_to_expr(property.values[0])
            return ast.Or(exprs=[property_to_expr(p) for p in property.values])
        raise NotImplementedError(f'PropertyGroup of unknown type "{property.type}"')
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
    if operator == PropertyOperator.exact:
        return ast.CompareOperationType.Eq, value
    elif operator == PropertyOperator.is_not or operator == PropertyOperator.is_date_exact:
        return ast.CompareOperationType.NotEq, value
    elif operator == PropertyOperator.is_set:
        return ast.CompareOperationType.NotEq, None
    elif operator == PropertyOperator.is_not_set:
        return ast.CompareOperationType.Eq, None
    elif operator == PropertyOperator.lt or operator == PropertyOperator.is_date_before:
        return ast.CompareOperationType.Lt, value
    elif operator == PropertyOperator.gt or operator == PropertyOperator.is_date_after:
        return ast.CompareOperationType.Gt, value
    elif operator == PropertyOperator.lte:
        return ast.CompareOperationType.LtE, value
    elif operator == PropertyOperator.gte:
        return ast.CompareOperationType.GtE, value
    elif operator == PropertyOperator.icontains:
        return ast.CompareOperationType.ILike, f"%{value}%"
    elif operator == PropertyOperator.not_icontains:
        return ast.CompareOperationType.NotILike, f"%{value}%"
    elif operator == PropertyOperator.regex:
        return ast.CompareOperationType.Regex, value
    elif operator == PropertyOperator.not_regex:
        return ast.CompareOperationType.NotRegex, value

    raise NotImplementedError(f"PropertyOperator {operator} not implemented")


def action_to_expr(action: Action) -> ast.Expr:
    steps = action.steps.all()

    if len(steps) == 0:
        return ast.Constant(value=True)

    or_queries = []
    for step in steps:
        exprs: List[ast.Expr] = [parse_expr("event = {event}", {"event": ast.Constant(value=step.event)})]

        if step.event == AUTOCAPTURE_EVENT:
            if step.selector:
                regex = build_selector_regex(Selector(step.selector, escape_slashes=False))
                expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=regex)})
                exprs.append(expr)
            if step.tag_name is not None:
                regex = rf"(^|;){step.tag_name}(\.|$|;|:)"
                expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(regex))})
                exprs.append(expr)
            if step.href is not None:
                href = str(re.escape(step.href.replace('"', r"\"")))
                expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=f'(href="{href}")')})
                exprs.append(expr)
            if step.text is not None:
                text = str(re.escape(step.text.replace('"', r"\"")))
                expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=f'(text="{text}")')})
                exprs.append(expr)

        if step.url:
            if step.url_matching == ActionStep.EXACT:
                expr = parse_expr("properties.$current_url = {url}", {"url": ast.Constant(value=step.url)})
            elif step.url_matching == ActionStep.REGEX:
                expr = parse_expr("match(properties.$current_url, {regex})", {"regex": ast.Constant(value=step.url)})
            else:
                expr = parse_expr("properties.$current_url like {url}", {"url": ast.Constant(value=f"%{step.url}%")})
            exprs.append(expr)

        if step.properties:
            exprs.append(property_to_expr(step.properties))

        if len(exprs) == 1:
            or_queries.append(exprs[0])
        elif len(exprs) > 1:
            or_queries.append(ast.And(exprs=exprs))

    if len(or_queries) == 1:
        return or_queries[0]
    else:
        return ast.Or(exprs=or_queries)
