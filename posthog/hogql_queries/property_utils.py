from typing import Literal, Optional, cast
from pydantic import BaseModel

from posthog.constants import (
    AUTOCAPTURE_EVENT,
    TREND_FILTER_TYPE_ACTIONS,
    PropertyOperatorType,
)
from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.models import (
    TeamDataClass,
    ActionDataClass,
    CohortDataClass,
    PropertyDefinitionDataClass,
    ElementDataClass,
)
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor, clone_expr
from posthog.models import Property
from posthog.models.element import Element
from posthog.models.event import Selector
from posthog.models.property import PropertyGroup, ValueT
from posthog.models.property.util import build_selector_regex
from posthog.models.property_definition import PropertyType
from posthog.schema import (
    EventMetadataPropertyFilter,
    RevenueAnalyticsPropertyFilter,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RetentionEntity,
    EventPropertyFilter,
    PersonPropertyFilter,
    ElementPropertyFilter,
    SessionPropertyFilter,
    CohortPropertyFilter,
    RecordingPropertyFilter,
    LogEntryPropertyFilter,
    GroupPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    HogQLPropertyFilter,
    EmptyPropertyFilter,
    DataWarehousePropertyFilter,
    DataWarehousePersonPropertyFilter,
    ErrorTrackingIssueFilter,
    LogPropertyFilter,
)
from posthog.utils import get_from_dict_or_attr
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
)


def has_aggregation(expr: AST) -> bool:
    """Check if an AST expression contains aggregation functions"""
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

    def visit_select_query(self, node: ast.SelectQuery):
        pass

    def visit_call(self, node: ast.Call):
        if find_hogql_aggregation(node.name):
            self.has_aggregation = True
        else:
            for arg in node.args:
                self.visit(arg)


def _handle_bool_values(value: ValueT, expr: ast.Expr, property: Property, team: TeamDataClass) -> ValueT | bool:
    """Handle boolean value conversion for properties based on property definitions"""
    if value != "true" and value != "false":
        return value
    
    # Since we're not using ORM, we need to get property definitions from context
    # This is a simplified implementation - in practice you'd need to inject
    # property definitions or get them from a service
    
    if property.type == "person" or property.type == "group" or property.type == "event":
        # For now, assume string properties that look like booleans should be converted
        if value == "true":
            return True
        if value == "false":
            return False
    
    return value


def _expr_to_compare_op(
    expr: ast.Expr, value: ValueT, operator: PropertyOperator, property: Property, is_json_field: bool, team: TeamDataClass
) -> ast.Expr:
    """Convert property comparison to AST expression"""
    if operator == PropertyOperator.IS_SET:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=None),
        )
    elif operator == PropertyOperator.IS_NOT_SET:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=expr,
                right=ast.Constant(value=None),
            )
        ]

        if is_json_field:
            if not isinstance(expr, ast.Field):
                raise Exception(f"Requires a Field expression")

            field = ast.Field(chain=expr.chain[:-1])

            exprs.append(
                ast.Not(
                    expr=ast.Call(
                        name="JSONHas",
                        args=[field, ast.Constant(value=property.key)],
                    )
                )
            )

        return ast.Or(exprs=exprs)
    elif operator == PropertyOperator.ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.ILike,
            left=ast.Call(name="toString", args=[expr]),
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == PropertyOperator.NOT_ICONTAINS:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotILike,
            left=ast.Call(name="toString", args=[expr]),
            right=ast.Constant(value=f"%{value}%"),
        )
    elif operator == PropertyOperator.REGEX:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="match", args=[expr, ast.Constant(value=value)]),
                ast.Constant(value=0),
            ],
        )
    elif operator == PropertyOperator.NOT_REGEX:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(name="match", args=[ast.Call(name="toString", args=[expr]), ast.Constant(value=value)])
                    ],
                ),
                ast.Constant(value=1),
            ],
        )
    elif operator == PropertyOperator.EXACT or operator == PropertyOperator.IS_DATE_EXACT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=expr,
            right=ast.Constant(value=_handle_bool_values(value, expr, property, team)),
        )
    elif operator == PropertyOperator.IS_NOT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=_handle_bool_values(value, expr, property, team)),
        )
    elif operator == PropertyOperator.LT or operator == PropertyOperator.IS_DATE_BEFORE:
        return ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.GT or operator == PropertyOperator.IS_DATE_AFTER:
        return ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.LTE:
        return ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.GTE:
        return ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.IS_CLEANED_PATH_EXACT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=apply_path_cleaning(expr, team),
            right=apply_path_cleaning(ast.Constant(value=value), team),
        )
    elif operator == PropertyOperator.IN_ or operator == PropertyOperator.NOT_IN:
        if not isinstance(value, list):
            raise Exception("IN and NOT IN operators require a list of values")
        op = ast.CompareOperationOp.NotIn if operator == PropertyOperator.NOT_IN else ast.CompareOperationOp.In
        return ast.CompareOperation(op=op, left=expr, right=ast.Array(exprs=[ast.Constant(value=v) for v in value]))
    else:
        raise NotImplementedError(f"PropertyOperator {operator} not implemented")


def apply_path_cleaning(path_expr: ast.Expr, team: TeamDataClass) -> ast.Expr:
    """Apply path cleaning filters to expression"""
    if not team.path_cleaning_filters:
        return path_expr

    for replacement in team.path_cleaning_filter_models():
        path_expr = ast.Call(
            name="replaceRegexpAll",
            args=[
                path_expr,
                ast.Constant(value=replacement.get("regex", "")),
                ast.Constant(value=replacement.get("alias", "")),
            ],
        )

    return path_expr


def map_virtual_properties(e: ast.Expr):
    """Map virtual properties to their actual field names"""
    if (
        isinstance(e, ast.Field)
        and len(e.chain) >= 2
        and e.chain[-2] == "properties"
        and isinstance(e.chain[-1], str)
        and e.chain[-1].startswith("$virt")
    ):
        return ast.Field(chain=e.chain[:-2] + [e.chain[-1]])
    return e


def create_expr_for_revenue_analytics_property(property: RevenueAnalyticsPropertyFilter) -> ast.Expr:
    """Create expression for revenue analytics properties"""
    if property.key == "amount":
        return ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "amount"])
    elif property.key == "country":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "country"])
    elif property.key == "cohort":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "cohort"])
    elif property.key == "coupon":
        return ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "coupon"])
    elif property.key == "coupon_id":
        return ast.Field(chain=[RevenueAnalyticsInvoiceItemView.get_generic_view_alias(), "coupon_id"])
    elif property.key == "initial_coupon":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "initial_coupon"])
    elif property.key == "initial_coupon_id":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "initial_coupon_id"])
    elif property.key == "product":
        return ast.Field(chain=[RevenueAnalyticsProductView.get_generic_view_alias(), "name"])
    elif property.key == "source":
        return ast.Field(chain=[RevenueAnalyticsCustomerView.get_generic_view_alias(), "source_label"])
    else:
        raise QueryError(f"Revenue analytics property filter key {property.key} not implemented")


def action_to_expr(action: ActionDataClass, events_alias: Optional[str] = None) -> ast.Expr:
    """Convert action to HogQL expression"""
    steps = action.steps

    if len(steps) == 0:
        return ast.Constant(value=True)

    or_queries = []
    for step in steps:
        exprs: list[ast.Expr] = []
        if step.event:
            exprs.append(parse_expr("event = {event}", {"event": ast.Constant(value=step.event)}))

        if step.event == AUTOCAPTURE_EVENT:
            if step.selector:
                exprs.append(selector_to_expr(step.selector))
            if step.tag_name is not None:
                exprs.append(tag_name_to_expr(step.tag_name))
            if step.href is not None:
                if step.href_matching == "regex":
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Regex,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=step.href),
                        )
                    )
                elif step.href_matching == "contains":
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=f"%{step.href}%"),
                        )
                    )
                else:
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["elements_chain_href"]),
                            right=ast.Constant(value=step.href),
                        )
                    )
            if step.text is not None:
                value = step.text
                if step.text_matching == "regex":
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x =~ {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=value)},
                        )
                    )
                elif step.text_matching == "contains":
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x ilike {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=f"%{value}%")},
                        )
                    )
                else:
                    exprs.append(
                        parse_expr(
                            "arrayExists(x -> x = {value}, elements_chain_texts)",
                            {"value": ast.Constant(value=value)},
                        )
                    )

        if step.url:
            if step.url_matching == "exact":
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=step.url),
                )
            elif step.url_matching == "regex":
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Regex,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=step.url),
                )
            else:
                expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Like,
                    left=ast.Field(
                        chain=(
                            [events_alias, "properties", "$current_url"]
                            if events_alias
                            else ["properties", "$current_url"]
                        )
                    ),
                    right=ast.Constant(value=f"%{step.url}%"),
                )
            exprs.append(expr)

        if step.properties:
            # This would need to be updated to use the new property_to_expr function
            from posthog.hogql.property import property_to_expr
            exprs.append(property_to_expr(step.properties, action.team))

        if len(exprs) == 1:
            or_queries.append(exprs[0])
        elif len(exprs) > 1:
            or_queries.append(ast.And(exprs=exprs))
        else:
            or_queries.append(ast.Constant(value=True))

    if len(or_queries) == 1:
        return or_queries[0]
    else:
        return ast.Or(exprs=or_queries)


def entity_to_expr(entity: RetentionEntity, team: TeamDataClass) -> ast.Expr:
    """Convert retention entity to HogQL expression"""
    if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
        # This would need to get action data from context/service
        # For now, simplified implementation
        return ast.Constant(value=True)
    
    if entity.id is None:
        return ast.Constant(value=True)

    filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value=entity.id),
        )
    ]

    if entity.properties is not None and entity.properties != []:
        # This would need to be updated to use the new property_to_expr function
        from posthog.hogql.property import property_to_expr
        filters.append(property_to_expr(entity.properties, team))

    return ast.And(exprs=filters)


def tag_name_to_expr(tag_name: str):
    """Convert tag name to HogQL expression"""
    regex = rf"(^|;){tag_name}(\.|$|;|:)"
    expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(regex))})
    return expr


def selector_to_expr(selector_string: str):
    """Convert selector to HogQL expression"""
    selector = Selector(selector_string, escape_slashes=False)
    exprs = []
    regex = build_selector_regex(selector)
    exprs.append(parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=regex)}))

    useful_elements: list[ast.Expr] = []
    for part in selector.parts:
        if "tag_name" in part.data:
            if part.data["tag_name"] in ElementDataClass.USEFUL_ELEMENTS:
                useful_elements.append(ast.Constant(value=part.data["tag_name"]))

        if "attr_id" in part.data:
            id_expr = parse_expr(
                "indexOf(elements_chain_ids, {value}) > 0", {"value": ast.Constant(value=part.data["attr_id"])}
            )
            if len(selector.parts) == 1 and len(part.data.keys()) == 1:
                return id_expr
            exprs.append(id_expr)
    
    if len(useful_elements) > 0:
        exprs.append(
            parse_expr(
                "arrayCount(x -> x IN {value}, elements_chain_elements) > 0",
                {"value": ast.Array(exprs=useful_elements)},
            )
        )

    if len(exprs) == 1:
        return exprs[0]
    return ast.And(exprs=exprs)


def get_property_type(property):
    """Get property type from property dict or object"""
    return get_from_dict_or_attr(property, "type")


def get_property_key(property):
    """Get property key from property dict or object"""
    return get_from_dict_or_attr(property, "key")


def get_property_value(property):
    """Get property value from property dict or object"""
    return get_from_dict_or_attr(property, "value")


def get_property_operator(property):
    """Get property operator from property dict or object"""
    return get_from_dict_or_attr(property, "operator")