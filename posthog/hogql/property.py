import re
from typing import Any, List, Optional, Union, cast

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

    if property.type == "hogql":
        return parse_expr(property.key)
    elif property.type == "event" or cast(Any, property.type) == "feature" or property.type == "person":
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.exact
        value = property.value
        if isinstance(value, list):
            if len(value) == 1:
                value = value[0]
            else:
                exprs = [
                    property_to_expr(
                        Property(type=property.type, key=property.key, operator=property.operator, value=v)
                    )
                    for v in value
                ]
                if (
                    operator == PropertyOperator.is_not
                    or operator == PropertyOperator.not_icontains
                    or operator == PropertyOperator.not_regex
                ):
                    return ast.And(exprs=exprs)
                return ast.Or(exprs=exprs)

        chain = ["person", "properties"] if property.type == "person" else ["properties"]
        field = ast.Field(chain=chain + [property.key])

        if operator == PropertyOperator.is_set:
            return ast.CompareOperation(op=ast.CompareOperationType.NotEq, left=field, right=ast.Constant(value=None))
        elif operator == PropertyOperator.is_not_set:
            return ast.CompareOperation(op=ast.CompareOperationType.Eq, left=field, right=ast.Constant(value=None))
        elif operator == PropertyOperator.icontains:
            return ast.CompareOperation(
                op=ast.CompareOperationType.ILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == PropertyOperator.not_icontains:
            return ast.CompareOperation(
                op=ast.CompareOperationType.NotILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == PropertyOperator.regex:
            return ast.Call(name="match", args=[field, ast.Constant(value=value)])
        elif operator == PropertyOperator.not_regex:
            return ast.Call(name="not", args=[ast.Call(name="match", args=[field, ast.Constant(value=value)])])
        elif operator == PropertyOperator.exact or operator == PropertyOperator.is_date_exact:
            op = ast.CompareOperationType.Eq
        elif operator == PropertyOperator.is_not:
            op = ast.CompareOperationType.NotEq
        elif operator == PropertyOperator.lt or operator == PropertyOperator.is_date_before:
            op = ast.CompareOperationType.Lt
        elif operator == PropertyOperator.gt or operator == PropertyOperator.is_date_after:
            op = ast.CompareOperationType.Gt
        elif operator == PropertyOperator.lte:
            op = ast.CompareOperationType.LtE
        elif operator == PropertyOperator.gte:
            op = ast.CompareOperationType.GtE
        else:
            raise NotImplementedError(f"PropertyOperator {operator} not implemented")

        return ast.CompareOperation(op=op, left=field, right=ast.Constant(value=value))

    elif property.type == "element":
        value = property.value
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.exact
        if isinstance(value, list):
            if len(value) == 1:
                value = value[0]
            else:
                exprs = [
                    property_to_expr(
                        Property(type=property.type, key=property.key, operator=property.operator, value=v)
                    )
                    for v in value
                ]
                if (
                    operator == PropertyOperator.is_not
                    or operator == PropertyOperator.not_icontains
                    or operator == PropertyOperator.not_regex
                ):
                    return ast.And(exprs=exprs)
                return ast.Or(exprs=exprs)

        if property.key == "selector" or property.key == "tag_name":
            if operator != PropertyOperator.exact and operator != PropertyOperator.is_not:
                raise NotImplementedError(
                    f"property_to_expr for element {property.key} only supports exact and is_not operators, not {operator}"
                )
            expr = selector_to_expr(str(value)) if property.key == "selector" else tag_name_to_expr(str(value))
            if operator == PropertyOperator.is_not:
                return ast.Call(name="not", args=[expr])
            return expr

        if property.key == "href":
            return element_chain_key_filter("href", str(value), operator)

        if property.key == "text":
            return element_chain_key_filter("text", str(value), operator)

        raise NotImplementedError(f"property_to_expr for type element not implemented for key {property.key}")
    # "cohort",
    # "element",
    # "static-cohort",
    # "precalculated-cohort",
    # "group",
    # "recording",
    # "behavioral",
    # "session",

    raise NotImplementedError(f"property_to_expr not implemented for filter type {type(property).__name__}")


def action_to_expr(action: Action) -> ast.Expr:
    steps = action.steps.all()

    if len(steps) == 0:
        return ast.Constant(value=True)

    or_queries = []
    for step in steps:
        exprs: List[ast.Expr] = [parse_expr("event = {event}", {"event": ast.Constant(value=step.event)})]

        if step.event == AUTOCAPTURE_EVENT:
            if step.selector:
                exprs.append(selector_to_expr(step.selector))
            if step.tag_name is not None:
                exprs.append(tag_name_to_expr(step.tag_name))
            if step.href is not None:
                exprs.append(element_chain_key_filter("href", step.href, PropertyOperator.exact))
            if step.text is not None:
                exprs.append(element_chain_key_filter("text", step.text, PropertyOperator.exact))

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


def element_chain_key_filter(key: str, text: str, operator: PropertyOperator):
    escaped = text.replace('"', r"\"")
    if operator == PropertyOperator.is_set or operator == PropertyOperator.is_not_set:
        value = r'[^"]+'
    elif operator == PropertyOperator.icontains or operator == PropertyOperator.not_icontains:
        value = rf'[^"]*{re.escape(escaped)}[^"]*'
    elif operator == PropertyOperator.regex or operator == PropertyOperator.not_regex:
        value = escaped
    elif operator == PropertyOperator.exact or operator == PropertyOperator.is_not:
        value = re.escape(escaped)
    else:
        raise NotImplementedError(f"element_href_to_expr not implemented for operator {operator}")
    optional_flag = (
        "(?i)" if operator == PropertyOperator.icontains or operator == PropertyOperator.not_icontains else ""
    )
    regex = f'{optional_flag}({key}="{value}")'
    expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(regex))})
    if (
        operator == PropertyOperator.is_not_set
        or operator == PropertyOperator.not_icontains
        or operator == PropertyOperator.is_not
        or operator == PropertyOperator.not_regex
    ):
        expr = ast.Call(name="not", args=[expr])
    return expr


def tag_name_to_expr(tag_name: str):
    regex = rf"(^|;){tag_name}(\.|$|;|:)"
    expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(regex))})
    return expr


def selector_to_expr(selector: str):
    regex = build_selector_regex(Selector(selector, escape_slashes=False))
    expr = parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=regex)})
    return expr
