import re
from typing import Literal, Optional, Union, cast

from pydantic import BaseModel

from posthog.constants import (
    AUTOCAPTURE_EVENT,
    TREND_FILTER_TYPE_ACTIONS,
    PropertyOperatorType,
)
from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.errors import NotImplementedError
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor, clone_expr
from posthog.models import (
    Action,
    Cohort,
    Property,
    PropertyDefinition,
    Team,
)
from posthog.models.event import Selector
from posthog.models.property import PropertyGroup
from posthog.models.property.util import build_selector_regex
from posthog.models.property_definition import PropertyType
from posthog.schema import (
    EmptyPropertyFilter,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RetentionEntity,
)
from posthog.warehouse.models import DataWarehouseJoin, DataWarehouseSavedQuery, DataWarehouseTable
from posthog.utils import get_from_dict_or_attr
from django.db.models import Q


def has_aggregation(expr: AST) -> bool:
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
        # don't care about aggregations in subqueries
        pass

    def visit_call(self, node: ast.Call):
        if find_hogql_aggregation(node.name):
            self.has_aggregation = True
        else:
            for arg in node.args:
                self.visit(arg)


def property_to_expr(
    property: Union[BaseModel, PropertyGroup, Property, dict, list, ast.Expr],
    team: Team,
    scope: Literal["event", "person", "session", "replay", "replay_entity"] = "event",
) -> ast.Expr:
    if isinstance(property, dict):
        try:
            property = Property(**property)
        # The property was saved as an incomplete object. Instead of crashing the entire query, pretend it's not there.
        # TODO: revert this when removing legacy insights?
        except ValueError:
            return ast.Constant(value=True)
        except TypeError:
            return ast.Constant(value=True)
    elif isinstance(property, list):
        properties = [property_to_expr(p, team, scope) for p in property]
        if len(properties) == 0:
            return ast.Constant(value=True)
        if len(properties) == 1:
            return properties[0]
        return ast.And(exprs=properties)
    elif isinstance(property, Property):
        pass
    elif isinstance(property, ast.Expr):
        return clone_expr(property)
    elif (
        isinstance(property, PropertyGroup)
        or isinstance(property, PropertyGroupFilter)
        or isinstance(property, PropertyGroupFilterValue)
    ):
        if (
            isinstance(property, PropertyGroup)
            and property.type != PropertyOperatorType.AND
            and property.type != PropertyOperatorType.OR
        ):
            raise NotImplementedError(f'PropertyGroup of unknown type "{property.type}"')
        if (
            (isinstance(property, PropertyGroupFilter) or isinstance(property, PropertyGroupFilterValue))
            and property.type != FilterLogicalOperator.AND_
            and property.type != FilterLogicalOperator.OR_
        ):
            raise NotImplementedError(f'PropertyGroupFilter of unknown type "{property.type}"')

        if len(property.values) == 0:
            return ast.Constant(value=True)
        if len(property.values) == 1:
            return property_to_expr(property.values[0], team, scope)

        if property.type == PropertyOperatorType.AND or property.type == FilterLogicalOperator.AND_:
            return ast.And(exprs=[property_to_expr(p, team, scope) for p in property.values])
        else:
            return ast.Or(exprs=[property_to_expr(p, team, scope) for p in property.values])
    elif isinstance(property, EmptyPropertyFilter):
        return ast.Constant(value=True)
    elif isinstance(property, BaseModel):
        try:
            property = Property(**property.dict())
        except ValueError:
            # The property was saved as an incomplete object. Instead of crashing the entire query, pretend it's not there.
            return ast.Constant(value=True)
    else:
        raise NotImplementedError(f"property_to_expr with property of type {type(property).__name__} not implemented")

    if property.type == "hogql":
        return parse_expr(property.key)
    elif (
        property.type == "event"
        or property.type == "feature"
        or property.type == "person"
        or property.type == "group"
        or property.type == "data_warehouse"
        or property.type == "data_warehouse_person_property"
        or property.type == "session"
    ):
        if (scope == "person" and property.type != "person") or (scope == "session" and property.type != "session"):
            raise NotImplementedError(f"The '{property.type}' property filter does not work in '{scope}' scope")
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.EXACT
        value = property.value

        if property.type == "person" and scope != "person":
            chain = ["person", "properties"]
        elif property.type == "event" and scope == "replay_entity":
            chain = ["events", "properties"]
        elif property.type == "session" and scope == "replay_entity":
            chain = ["events", "session"]
        elif property.type == "data_warehouse_person_property":
            if isinstance(property.key, str):
                table, key = property.key.split(": ")
                chain = ["person", table]
                property.key = key
            else:
                raise NotImplementedError("Data warehouse person property filter value must be a string")
        elif property.type == "group":
            chain = [f"group_{property.group_type_index}", "properties"]
        elif property.type == "data_warehouse":
            chain = []
        elif property.type == "session" and scope in ["event", "replay"]:
            chain = ["session"]
        elif property.type == "session" and scope == "session":
            chain = ["sessions"]
        else:
            chain = ["properties"]

        properties_field = ast.Field(chain=chain)
        field = ast.Field(chain=[*chain, property.key])

        if isinstance(value, list):
            if len(value) == 0:
                return ast.Constant(value=True)
            elif len(value) == 1:
                value = value[0]
            else:
                # Using an AND here instead of `in()` or `notIn()`, due to Clickhouses poor handling of `null` values
                exprs = [
                    property_to_expr(
                        Property(
                            type=property.type,
                            key=property.key,
                            operator=property.operator,
                            group_type_index=property.group_type_index,
                            value=v,
                        ),
                        team,
                        scope,
                    )
                    for v in value
                ]
                if (
                    operator == PropertyOperator.NOT_ICONTAINS
                    or operator == PropertyOperator.NOT_REGEX
                    or operator == PropertyOperator.IS_NOT
                ):
                    return ast.And(exprs=exprs)
                return ast.Or(exprs=exprs)

        if operator == PropertyOperator.IS_SET:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=field,
                right=ast.Constant(value=None),
            )
        elif operator == PropertyOperator.IS_NOT_SET:
            return ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=field,
                        right=ast.Constant(value=None),
                    )
                ]
                + (
                    []
                    if properties_field == field
                    else [
                        ast.Not(
                            expr=ast.Call(
                                name="JSONHas",
                                args=[properties_field, ast.Constant(value=property.key)],
                            )
                        )
                    ]
                )
            )
        elif operator == PropertyOperator.ICONTAINS:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.ILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == PropertyOperator.NOT_ICONTAINS:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == PropertyOperator.REGEX:
            return ast.Call(
                name="ifNull",
                args=[
                    ast.Call(name="match", args=[ast.Call(name="toString", args=[field]), ast.Constant(value=value)]),
                    ast.Constant(value=False),
                ],
            )
        elif operator == PropertyOperator.NOT_REGEX:
            return ast.Call(
                name="ifNull",
                args=[
                    ast.Call(
                        name="not",
                        args=[
                            ast.Call(
                                name="match", args=[ast.Call(name="toString", args=[field]), ast.Constant(value=value)]
                            )
                        ],
                    ),
                    ast.Constant(value=True),
                ],
            )
        elif operator == PropertyOperator.EXACT or operator == PropertyOperator.IS_DATE_EXACT:
            op = ast.CompareOperationOp.Eq
        elif operator == PropertyOperator.IS_NOT:
            op = ast.CompareOperationOp.NotEq
        elif operator == PropertyOperator.LT or operator == PropertyOperator.IS_DATE_BEFORE:
            op = ast.CompareOperationOp.Lt
        elif operator == PropertyOperator.GT or operator == PropertyOperator.IS_DATE_AFTER:
            op = ast.CompareOperationOp.Gt
        elif operator == PropertyOperator.LTE:
            op = ast.CompareOperationOp.LtEq
        elif operator == PropertyOperator.GTE:
            op = ast.CompareOperationOp.GtEq
        else:
            raise NotImplementedError(f"PropertyOperator {operator} not implemented")

        # For Boolean and untyped properties, treat "true" and "false" as boolean values
        if (
            (op == ast.CompareOperationOp.Eq or op == ast.CompareOperationOp.NotEq)
            and team is not None
            and (value == "true" or value == "false")
        ):
            if property.type == "person":
                property_types = PropertyDefinition.objects.filter(
                    team=team,
                    name=property.key,
                    type=PropertyDefinition.Type.PERSON,
                )
            elif property.type == "group":
                property_types = PropertyDefinition.objects.filter(
                    team=team,
                    name=property.key,
                    type=PropertyDefinition.Type.GROUP,
                    group_type_index=property.group_type_index,
                )
            elif property.type == "data_warehouse_person_property":
                key = chain[-1]

                # TODO: pass id of table item being filtered on instead of searching through joins
                current_join: DataWarehouseJoin | None = (
                    DataWarehouseJoin.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
                    .filter(team=team, source_table_name="persons", field_name=key)
                    .first()
                )

                if not current_join:
                    raise Exception(f"Could not find join for key {key}")

                prop_type = None

                maybe_view = (
                    DataWarehouseSavedQuery.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
                    .filter(team=team, name=current_join.joining_table_name)
                    .first()
                )

                if maybe_view:
                    prop_type_dict = maybe_view.columns.get(property.key, None)
                    prop_type = prop_type_dict.get("hogql")

                maybe_table = (
                    DataWarehouseTable.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
                    .filter(team=team, name=current_join.joining_table_name)
                    .first()
                )

                if maybe_table:
                    prop_type_dict = maybe_table.columns.get(property.key, None)
                    prop_type = prop_type_dict.get("hogql")

                if not maybe_view and not maybe_table:
                    raise Exception(f"Could not find table or view for key {key}")

                if prop_type == "BooleanDatabaseField":
                    if value == "true":
                        value = True
                    if value == "false":
                        value = False

                return ast.CompareOperation(op=op, left=field, right=ast.Constant(value=value))

            else:
                property_types = PropertyDefinition.objects.filter(
                    team=team,
                    name=property.key,
                    type=PropertyDefinition.Type.EVENT,
                )
            property_type = property_types[0].property_type if len(property_types) > 0 else None

            if property_type == PropertyType.Boolean:
                if value == "true":
                    value = True
                if value == "false":
                    value = False

        return ast.CompareOperation(op=op, left=field, right=ast.Constant(value=value))

    elif property.type == "element":
        if scope == "person":
            raise NotImplementedError(f"property_to_expr for scope {scope} not implemented for type '{property.type}'")
        value = property.value
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.EXACT
        if isinstance(value, list):
            if len(value) == 1:
                value = value[0]
            else:
                exprs = [
                    property_to_expr(
                        Property(
                            type=property.type,
                            key=property.key,
                            operator=property.operator,
                            group_type_index=property.group_type_index,
                            value=v,
                        ),
                        team,
                        scope,
                    )
                    for v in value
                ]
                if (
                    operator == PropertyOperator.IS_NOT
                    or operator == PropertyOperator.NOT_ICONTAINS
                    or operator == PropertyOperator.NOT_REGEX
                ):
                    return ast.And(exprs=exprs)
                return ast.Or(exprs=exprs)

        if property.key == "selector" or property.key == "tag_name":
            if operator != PropertyOperator.EXACT and operator != PropertyOperator.IS_NOT:
                raise NotImplementedError(
                    f"property_to_expr for element {property.key} only supports exact and is_not operators, not {operator}"
                )
            expr = selector_to_expr(str(value)) if property.key == "selector" else tag_name_to_expr(str(value))
            if operator == PropertyOperator.IS_NOT:
                return ast.Call(name="not", args=[expr])
            return expr

        if property.key == "href":
            return element_chain_key_filter("href", str(value), operator)

        if property.key == "text":
            return element_chain_key_filter("text", str(value), operator)

        raise NotImplementedError(f"property_to_expr for type element not implemented for key {property.key}")
    elif property.type == "cohort" or property.type == "static-cohort" or property.type == "precalculated-cohort":
        if not team:
            raise Exception("Can not convert cohort property to expression without team")
        cohort = Cohort.objects.get(team=team, id=property.value)
        return ast.CompareOperation(
            left=ast.Field(chain=["id" if scope == "person" else "person_id"]),
            op=ast.CompareOperationOp.InCohort,
            right=ast.Constant(value=cohort.pk),
        )

    # TODO: Add support for these types: "recording", "behavioral"

    raise NotImplementedError(
        f"property_to_expr not implemented for filter type {type(property).__name__} and {property.type}"
    )


def action_to_expr(action: Action) -> ast.Expr:
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
                    operator = PropertyOperator.REGEX
                elif step.href_matching == "contains":
                    operator = PropertyOperator.ICONTAINS
                else:
                    operator = PropertyOperator.EXACT
                exprs.append(element_chain_key_filter("href", step.href, operator))
            if step.text is not None:
                if step.text_matching == "regex":
                    operator = PropertyOperator.REGEX
                elif step.text_matching == "contains":
                    operator = PropertyOperator.ICONTAINS
                else:
                    operator = PropertyOperator.EXACT
                exprs.append(element_chain_key_filter("text", step.text, operator))

        if step.url:
            if step.url_matching == "exact":
                expr = parse_expr(
                    "properties.$current_url = {url}",
                    {"url": ast.Constant(value=step.url)},
                )
            elif step.url_matching == "regex":
                expr = parse_expr(
                    "properties.$current_url =~ {regex}",
                    {"regex": ast.Constant(value=step.url)},
                )
            else:
                expr = parse_expr(
                    "properties.$current_url like {url}",
                    {"url": ast.Constant(value=f"%{step.url}%")},
                )
            exprs.append(expr)

        if step.properties:
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


def entity_to_expr(entity: RetentionEntity) -> ast.Expr:
    if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
        action = Action.objects.get(pk=entity.id)
        return action_to_expr(action)
    if entity.id is None:
        return ast.Constant(value=True)

    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["events", "event"]),
        right=ast.Constant(value=entity.id),
    )


def element_chain_key_filter(key: str, text: str, operator: PropertyOperator):
    escaped = text.replace('"', r"\"")
    if operator == PropertyOperator.IS_SET or operator == PropertyOperator.IS_NOT_SET:
        value = r'[^"]+'
    elif operator == PropertyOperator.ICONTAINS or operator == PropertyOperator.NOT_ICONTAINS:
        value = rf'[^"]*{re.escape(escaped)}[^"]*'
    elif operator == PropertyOperator.REGEX or operator == PropertyOperator.NOT_REGEX:
        value = escaped
    elif operator == PropertyOperator.EXACT or operator == PropertyOperator.IS_NOT:
        value = re.escape(escaped)
    else:
        raise NotImplementedError(f"element_href_to_expr not implemented for operator {operator}")

    regex = f'({key}="{value}")'
    if operator == PropertyOperator.ICONTAINS or operator == PropertyOperator.NOT_ICONTAINS:
        expr = parse_expr("elements_chain =~* {regex}", {"regex": ast.Constant(value=str(regex))})
    else:
        expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(regex))})

    if (
        operator == PropertyOperator.IS_NOT_SET
        or operator == PropertyOperator.NOT_ICONTAINS
        or operator == PropertyOperator.IS_NOT
        or operator == PropertyOperator.NOT_REGEX
    ):
        expr = ast.Call(name="not", args=[expr])
    return expr


def tag_name_to_expr(tag_name: str):
    regex = rf"(^|;){tag_name}(\.|$|;|:)"
    expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(regex))})
    return expr


def selector_to_expr(selector: str):
    regex = build_selector_regex(Selector(selector, escape_slashes=False))
    expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=regex)})
    return expr


def get_property_type(property):
    return get_from_dict_or_attr(property, "type")


def get_property_key(property):
    return get_from_dict_or_attr(property, "key")


def get_property_value(property):
    return get_from_dict_or_attr(property, "value")


def get_property_operator(property):
    return get_from_dict_or_attr(property, "operator")
