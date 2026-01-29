import re
from collections.abc import Callable
from typing import Literal, Optional, TypeGuard, cast

from django.db import models
from django.db.models import Q
from django.db.models.functions.comparison import Coalesce

from pydantic import BaseModel

from posthog.schema import (
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    ErrorTrackingIssueFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FilterLogicalOperator,
    FlagPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
    RecordingPropertyFilter,
    RetentionEntity,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.hogql.functions import find_hogql_aggregation
from posthog.hogql.parser import parse_expr
from posthog.hogql.utils import map_virtual_properties
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS, PropertyOperatorType
from posthog.models import Action, Cohort, Property, PropertyDefinition, Team
from posthog.models.element import Element
from posthog.models.event import Selector
from posthog.models.property import PropertyGroup, ValueT
from posthog.models.property.util import build_selector_regex
from posthog.models.property_definition import PropertyType
from posthog.utils import get_from_dict_or_attr

from products.data_warehouse.backend.models import DataWarehouseJoin
from products.data_warehouse.backend.models.util import get_view_or_table_by_name


def parse_semver(value: str) -> tuple[str, str, str]:
    """
    Parse a semver string into (major, minor, patch) components.

    - Strips pre-release suffixes (e.g., -alpha.1)
    - Defaults missing components to "0" (e.g., 1.0 -> 1.0.0)

    Returns tuple of strings for direct use in version string construction.
    Raises ValueError if parsing fails.
    """
    # Strip pre-release suffix (everything after first hyphen)
    base_version = value.split("-")[0]

    parts = base_version.split(".")
    if len(parts) < 1 or not parts[0]:
        raise ValueError("Invalid semver format")

    major = parts[0]
    minor = parts[1] if len(parts) > 1 else "0"
    patch = parts[2] if len(parts) > 2 else "0"

    # Validate they're actually integers
    int(major), int(minor), int(patch)

    return (major, minor, patch)


def semver_range_compare(
    expr: ast.Expr,
    value: ast.Any,
    operator_name: str,
    bounds_calculator: Callable[[str], tuple[str, str]],
) -> ast.And:
    """
    Build a semver range comparison AST (lower_bound <= expr < upper_bound).

    Args:
        expr: The expression to compare (e.g., person.properties.app_version)
        value: The semver value from the filter
        operator_name: Name for error messages (e.g., "Tilde", "Caret", "Wildcard")
        bounds_calculator: Function that takes the value and returns (lower_bound, upper_bound)

    Returns:
        AST node representing: sortableSemver(expr) >= sortableSemver(lower) AND sortableSemver(expr) < sortableSemver(upper)
    """
    if not isinstance(value, str):
        raise QueryError(f"{operator_name} operator requires a semver string value")

    try:
        lower_bound, upper_bound = bounds_calculator(value)
    except (ValueError, IndexError):
        raise QueryError(f"{operator_name} operator requires a valid semver string (e.g., '1.2.3')")

    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Call(name="sortableSemver", args=[expr]),
                right=ast.Call(name="sortableSemver", args=[ast.Constant(value=lower_bound)]),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Call(name="sortableSemver", args=[expr]),
                right=ast.Call(name="sortableSemver", args=[ast.Constant(value=upper_bound)]),
            ),
        ]
    )


def _tilde_bounds(value: str) -> tuple[str, str]:
    """~1.2.3 means >=1.2.3 <1.3.0 (allows patch-level changes)"""
    parts = value.split("-")[0].split(".")
    if len(parts) < 2:
        raise ValueError("Tilde operator requires at least major.minor version")
    major, minor, patch = parse_semver(value)
    next_minor = str(int(minor) + 1)
    return f"{major}.{minor}.{patch}", f"{major}.{next_minor}.0"


def _caret_bounds(value: str) -> tuple[str, str]:
    """
    Caret operator follows semver spec:
    ^1.2.3 means >=1.2.3 <2.0.0
    ^0.2.3 means >=0.2.3 <0.3.0
    ^0.0.3 means >=0.0.3 <0.0.4
    The leftmost non-zero component determines the upper bound.
    """
    major, minor, patch = parse_semver(value)
    lower_bound = f"{major}.{minor}.{patch}"

    if int(major) > 0:
        upper_bound = f"{int(major) + 1}.0.0"
    elif int(minor) > 0:
        upper_bound = f"0.{int(minor) + 1}.0"
    else:
        upper_bound = f"0.0.{int(patch) + 1}"

    return lower_bound, upper_bound


def _wildcard_bounds(value: str) -> tuple[str, str]:
    """
    Wildcard matching:
    1.* means >=1.0.0 <2.0.0
    1.2.* means >=1.2.0 <1.3.0
    1.2.3.* means >=1.2.3.0 <1.2.4.0
    """
    # Remove trailing .* if present
    value = value.rstrip(".*")
    if not value:
        raise ValueError("Invalid wildcard pattern")

    # Strip pre-release suffix before counting parts
    base_value = value.split("-")[0]
    parts = base_value.split(".")

    if len(parts) == 1:
        major = parts[0]
        int(major)  # Validate
        return f"{major}.0.0", f"{int(major) + 1}.0.0"
    elif len(parts) == 2:
        major, minor = parts[0], parts[1]
        int(major), int(minor)  # Validate
        return f"{major}.{minor}.0", f"{major}.{int(minor) + 1}.0"
    else:
        major, minor, patch = parts[0], parts[1], parts[2]
        int(major), int(minor), int(patch)  # Validate
        return f"{major}.{minor}.{patch}.0", f"{major}.{minor}.{int(patch) + 1}.0"


GROUP_KEY_PATTERN = re.compile(r"^\$group_[0-4]$")


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


def _handle_bool_values(value: ValueT, expr: ast.Expr, property: Property, team: Team) -> ValueT | bool:
    if value is True:
        value = "true"
    elif value is False:
        value = "false"

    if value != "true" and value != "false":
        return value
    if property.type == "person":
        property_types = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(
            effective_project_id=team.project_id,
            name=property.key,
            type=PropertyDefinition.Type.PERSON,
        )
    elif property.type == "group":
        property_types = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(
            effective_project_id=team.project_id,
            name=property.key,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=property.group_type_index,
        )
    elif property.type == "data_warehouse_person_property":
        if not isinstance(expr, ast.Field):
            raise Exception(f"Requires a Field expression")

        key = expr.chain[-2]

        # TODO: pass id of table item being filtered on instead of searching through joins
        current_join: DataWarehouseJoin | None = (
            DataWarehouseJoin.objects.filter(Q(deleted__isnull=True) | Q(deleted=False))
            .filter(team=team, source_table_name="persons", field_name=key)
            .first()
        )

        if not current_join:
            raise Exception(f"Could not find join for key {key}")

        prop_type = None

        table_or_view = get_view_or_table_by_name(team, current_join.joining_table_name)
        if table_or_view:
            prop_type_dict = table_or_view.columns.get(property.key, None)
            prop_type = prop_type_dict.get("hogql")

        if not table_or_view:
            raise Exception(f"Could not find table or view for key {key}")

        if prop_type == "BooleanDatabaseField":
            if value == "true":
                value = True
            if value == "false":
                value = False

        return value

    else:
        property_types = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(
            effective_project_id=team.project_id,
            name=property.key,
            type=PropertyDefinition.Type.EVENT,
        )
    property_type = property_types[0].property_type if len(property_types) > 0 else None

    if property_type == PropertyType.Boolean:
        if value == "true":
            return True
        if value == "false":
            return False
    return value


def _validate_between_values(value: ValueT, operator: PropertyOperator) -> TypeGuard[list[str]]:
    if not isinstance(value, list) or len(value) != 2:
        raise QueryError(f"{operator} operator requires a two-element array [min, max]")
    try:
        if float(value[0]) > float(value[1]):
            raise QueryError(f"{operator} operator requires min value to be less than or equal to max value")
    except (ValueError, TypeError):
        raise QueryError(f"{operator} operator requires numeric values")
    return True


def _expr_to_compare_op(
    expr: ast.Expr, value: ValueT, operator: PropertyOperator, property: Property, is_json_field: bool, team: Team
) -> ast.Expr:
    if operator == PropertyOperator.IS_SET:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=expr,
            right=ast.Constant(value=None),
        )
    elif operator == PropertyOperator.IS_NOT_SET:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=expr,
            right=ast.Constant(value=None),
        )
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
                ast.Call(name="match", args=[ast.Call(name="toString", args=[expr]), ast.Constant(value=value)]),
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
    elif operator == PropertyOperator.LTE or operator == PropertyOperator.MAX:
        return ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.GTE or operator == PropertyOperator.MIN:
        return ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=expr, right=ast.Constant(value=value))
    elif operator == PropertyOperator.BETWEEN:
        _validate_between_values(value, operator)
        assert isinstance(value, list)
        return ast.And(
            exprs=[
                ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=expr, right=ast.Constant(value=value[0])),
                ast.CompareOperation(op=ast.CompareOperationOp.LtEq, left=expr, right=ast.Constant(value=value[1])),
            ]
        )
    elif operator == PropertyOperator.NOT_BETWEEN:
        _validate_between_values(value, operator)
        assert isinstance(value, list)
        return ast.Or(
            exprs=[
                ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=expr, right=ast.Constant(value=value[0])),
                ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=expr, right=ast.Constant(value=value[1])),
            ]
        )
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
    elif operator == PropertyOperator.SEMVER_EQ:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_NEQ:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_GT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_GTE:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_LT:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_LTE:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Call(name="sortableSemver", args=[expr]),
            right=ast.Call(name="sortableSemver", args=[ast.Constant(value=value)]),
        )
    elif operator == PropertyOperator.SEMVER_TILDE:
        return semver_range_compare(expr, value, "Tilde", _tilde_bounds)
    elif operator == PropertyOperator.SEMVER_CARET:
        return semver_range_compare(expr, value, "Caret", _caret_bounds)
    elif operator == PropertyOperator.SEMVER_WILDCARD:
        return semver_range_compare(expr, value, "Wildcard", _wildcard_bounds)
    else:
        raise NotImplementedError(f"PropertyOperator {operator} not implemented")


def apply_path_cleaning(path_expr: ast.Expr, team: Team) -> ast.Expr:
    if not team.path_cleaning_filters:
        return path_expr

    for replacement in team.path_cleaning_filter_models():
        path_expr = ast.Call(
            name="replaceRegexpAll",
            args=[
                path_expr,
                ast.Constant(value=replacement.regex),
                ast.Constant(value=replacement.alias),
            ],
        )

    return path_expr


def property_to_expr(
    property: (
        list
        | dict
        | PropertyGroup
        | PropertyGroupFilter
        | PropertyGroupFilterValue
        | Property
        | ast.Expr
        | EventPropertyFilter
        | PersonPropertyFilter
        | ElementPropertyFilter
        | SessionPropertyFilter
        | EventMetadataPropertyFilter
        | RevenueAnalyticsPropertyFilter
        | CohortPropertyFilter
        | RecordingPropertyFilter
        | LogEntryPropertyFilter
        | GroupPropertyFilter
        | FeaturePropertyFilter
        | FlagPropertyFilter
        | HogQLPropertyFilter
        | EmptyPropertyFilter
        | DataWarehousePropertyFilter
        | DataWarehousePersonPropertyFilter
        | ErrorTrackingIssueFilter
        | LogPropertyFilter
    ),
    team: Team,
    scope: Literal[
        "event", "person", "group", "session", "replay", "replay_entity", "revenue_analytics", "log_resource"
    ] = "event",
    strict: bool = False,
) -> ast.Expr:
    if isinstance(property, dict):
        try:
            property = Property(**property)
        # The property was saved as an incomplete object. Instead of crashing the entire query, pretend it's not there.
        # TODO: revert this when removing legacy insights?
        except ValueError:
            if strict:
                raise
            return ast.Constant(value=1)
        except TypeError:
            if strict:
                raise
            return ast.Constant(value=1)
    elif isinstance(property, list):
        properties = [property_to_expr(p, team, scope, strict=strict) for p in property]
        if len(properties) == 0:
            return ast.Constant(value=1)
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
            raise QueryError(f'PropertyGroup of unknown type "{property.type}"')
        if (
            (isinstance(property, PropertyGroupFilter) or isinstance(property, PropertyGroupFilterValue))
            and property.type != FilterLogicalOperator.AND_
            and property.type != FilterLogicalOperator.OR_
        ):
            raise QueryError(f'PropertyGroupFilter of unknown type "{property.type}"')

        if len(property.values) == 0:
            return ast.Constant(value=1)
        if len(property.values) == 1:
            return property_to_expr(property.values[0], team, scope, strict=strict)

        if property.type == PropertyOperatorType.AND or property.type == FilterLogicalOperator.AND_:
            return ast.And(exprs=[property_to_expr(p, team, scope, strict=strict) for p in property.values])
        else:
            return ast.Or(exprs=[property_to_expr(p, team, scope, strict=strict) for p in property.values])
    elif isinstance(property, EmptyPropertyFilter):
        return ast.Constant(value=1)
    elif isinstance(property, FlagPropertyFilter):
        # Flag dependencies are evaluated at the API layer, not in HogQL.
        # They should never reach this point, but we handle them gracefully
        # to satisfy type checking since FlagPropertyFilter is part
        # of the AnyPropertyFilter union used throughout the codebase.
        # Return a neutral filter that doesn't affect the query.
        return ast.Constant(value=1)
    elif isinstance(property, BaseModel):
        try:
            property = Property(**property.dict())
        except ValueError:
            if strict:
                raise
            # The property was saved as an incomplete object. Instead of crashing the entire query, pretend it's not there.
            return ast.Constant(value=1)
    else:
        raise QueryError(f"property_to_expr with property of type {type(property).__name__} not implemented")

    if property.type == "hogql":
        return parse_expr(property.key)
    elif property.type == "event_metadata" and scope == "group" and GROUP_KEY_PATTERN.match(property.key) is not None:
        group_type_index = property.key.split("_")[1]
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.EXACT
        value = property.value
        if isinstance(property.value, list):
            if len(property.value) > 1:
                raise QueryError(f"The '{property.key}' property filter only supports one value in 'group' scope")
            value = property.value[0]

        # For groups table, $group_N filters should match both index and key
        # index should equal N, and key should match the value
        index_condition = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["index"]),
            right=ast.Constant(value=int(group_type_index)),
        )

        key_condition = _expr_to_compare_op(
            expr=ast.Field(chain=["key"]),
            value=value,
            operator=operator,
            property=property,
            is_json_field=False,
            team=team,
        )

        return ast.And(exprs=[key_condition, index_condition])
    elif (
        property.type == "event"
        or property.type == "event_metadata"
        or property.type == "feature"
        or property.type == "person"
        or property.type == "group"
        or property.type == "behavioral"
        or property.type == "data_warehouse"
        or property.type == "data_warehouse_person_property"
        or property.type == "session"
        or property.type == "recording"
        or property.type == "log_entry"
        or property.type == "error_tracking_issue"
        or property.type == "log"
        or property.type == "log_attribute"
        or property.type == "log_resource_attribute"
        or property.type == "revenue_analytics"
        or property.type == "workflow_variable"
    ):
        if (
            (scope == "person" and property.type != "person")
            or (scope == "session" and property.type != "session")
            or (scope != "event" and property.type == "event_metadata")
            or (scope == "revenue_analytics" and property.type != "revenue_analytics")
            or (property.type == "revenue_analytics" and scope != "revenue_analytics")
        ):
            raise QueryError(f"The '{property.type}' property filter does not work in '{scope}' scope")
        operator = cast(Optional[PropertyOperator], property.operator) or PropertyOperator.EXACT
        value = property.value

        if property.type == "person" and scope != "person":
            chain = ["person", "properties"]
        elif property.type == "event" and scope == "replay_entity":
            chain = ["events", "properties"]
        elif property.type == "session" and scope == "replay_entity":
            chain = ["events", "session"]
        elif property.type == "data_warehouse":
            if not isinstance(property.key, str):
                raise QueryError("Data warehouse property filter value must be a string")
            else:
                split = property.key.split(".")
                chain = split[:-1]
                property.key = split[-1]

            if isinstance(value, list) and len(value) > 1:
                field = ast.Field(chain=[*chain, property.key])
                exprs = [
                    _expr_to_compare_op(
                        expr=field,
                        value=v,
                        operator=operator,
                        team=team,
                        property=property,
                        is_json_field=False,
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
        elif property.type == "data_warehouse_person_property":
            if isinstance(property.key, str):
                table, key = property.key.split(".")
                chain = ["person", table]
                property.key = key
            else:
                raise QueryError("Data warehouse person property filter value must be a string")
        elif property.type == "group" and scope != "group":
            chain = [f"group_{property.group_type_index}", "properties"]
        elif property.type == "session" and scope in ["event", "replay"]:
            chain = ["session"]
        elif property.type == "session" and scope == "session":
            chain = ["sessions"]
        elif property.type in ["recording", "data_warehouse", "log_entry", "event_metadata"]:
            chain = []
        elif property.type == "log":
            chain = [property.key]
            property.key = ""
        elif scope == "log_resource":
            # log resource attributes are stored in a separate table as `attribute_key` and `attribute_value`
            # columns. The `attribute_key` filter needs to be added separately outside of property_to_expr
            chain = ["attribute_value"]
            property.key = ""
        elif property.type == "log_attribute":
            chain = ["attributes"]
        elif property.type == "log_resource_attribute":
            chain = ["resource_attributes"]
        elif property.type == "revenue_analytics":
            *chain, property.key = property.key.split(".")
        elif property.type == "workflow_variable":
            chain = ["variables"]
        else:
            chain = ["properties"]

        # We pretend elements chain is a property, but it is actually a column on the events table
        if chain == ["properties"] and property.key == "$elements_chain":
            field = ast.Field(chain=["elements_chain"])
        elif property.key == "":
            field = ast.Field(chain=[*chain])
        else:
            field = ast.Field(chain=[*chain, property.key])

        expr: ast.Expr = map_virtual_properties(field)

        if property.type == "recording" and property.key == "snapshot_source":
            expr = ast.Call(name="argMinMerge", args=[field])

        is_visited_page_property = property.type == "recording" and property.key == "visited_page"
        if is_visited_page_property:
            # Use the all_urls array field to filter for pages visited during recording.
            all_urls_field = ast.Field(chain=["all_urls"])

        is_exception_string_array_property = property.type == "event" and property.key in [
            "$exception_types",
            "$exception_values",
            "$exception_sources",
            "$exception_functions",
        ]

        if is_exception_string_array_property:
            # if materialized these columns will be strings so we need to extract them
            extracted_field = ast.Call(
                name="JSONExtract",
                args=[
                    ast.Call(name="ifNull", args=[field, ast.Constant(value="")]),
                    ast.Constant(value="Array(String)"),
                ],
            )

        if isinstance(value, list) and operator not in (PropertyOperator.BETWEEN, PropertyOperator.NOT_BETWEEN):
            if len(value) == 0:
                return ast.Constant(value=1)
            elif len(value) == 1:
                value = value[0]
            else:
                if operator in (
                    PropertyOperator.EXACT,
                    PropertyOperator.IS_NOT,
                    PropertyOperator.IN_,
                    PropertyOperator.NOT_IN,
                ):
                    op = (
                        ast.CompareOperationOp.In
                        if operator in (PropertyOperator.EXACT, PropertyOperator.IN_)
                        else ast.CompareOperationOp.NotIn
                    )

                    left = (
                        ast.Field(chain=["v"])
                        if (is_exception_string_array_property or is_visited_page_property)
                        else expr
                    )
                    compare_op = ast.CompareOperation(
                        op=op, left=left, right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value])
                    )

                    if is_exception_string_array_property:
                        return parse_expr(
                            "arrayExists(v -> {compare_op}, {field})",
                            {
                                "compare_op": compare_op,
                                "field": extracted_field,
                            },
                        )
                    elif is_visited_page_property:
                        return parse_expr(
                            "arrayExists(v -> {compare_op}, {field})",
                            {
                                "compare_op": compare_op,
                                "field": all_urls_field,
                            },
                        )
                    else:
                        return compare_op

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
                        strict=strict,
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

        expr = _expr_to_compare_op(
            expr=ast.Field(chain=["v"]) if (is_exception_string_array_property or is_visited_page_property) else expr,
            value=value,
            operator=operator,
            team=team,
            property=property,
            is_json_field=property.type != "session",
        )

        if is_exception_string_array_property:
            return parse_expr(
                "arrayExists(v -> {expr}, {key})",
                {"expr": expr, "key": extracted_field},
            )
        elif is_visited_page_property:
            # Handle IS_SET and IS_NOT_SET operators specially for arrays
            if operator == PropertyOperator.IS_SET:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Call(name="length", args=[all_urls_field]),
                    right=ast.Constant(value=0),
                )
            elif operator == PropertyOperator.IS_NOT_SET:
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Call(name="length", args=[all_urls_field]),
                    right=ast.Constant(value=0),
                )
            else:
                return parse_expr(
                    "arrayExists(v -> {expr}, {key})",
                    {"expr": expr, "key": all_urls_field},
                )
        else:
            return expr
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
                        strict=strict,
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
            return _expr_to_compare_op(
                expr=ast.Field(chain=["elements_chain_href"]),
                value=value,
                operator=operator,
                team=team,
                property=property,
                is_json_field=False,
            )

        if property.key == "text":
            return parse_expr(
                "arrayExists(text -> {compare}, elements_chain_texts)",
                {
                    "compare": _expr_to_compare_op(
                        expr=ast.Field(chain=["text"]),
                        value=value,
                        operator=operator,
                        team=team,
                        property=property,
                        is_json_field=False,
                    )
                },
            )

        raise NotImplementedError(f"property_to_expr for type element not implemented for key {property.key}")
    elif property.type == "cohort" or property.type == "static-cohort" or property.type == "precalculated-cohort":
        if not team:
            raise Exception("Can not convert cohort property to expression without team")
        cohort = Cohort.objects.get(team__project_id=team.project_id, id=property.value)
        return ast.CompareOperation(
            left=ast.Field(chain=["id" if scope == "person" else "person_id"]),
            op=(
                ast.CompareOperationOp.NotInCohort
                # Kludge: negation is outdated but still used in places
                if property.negation or property.operator == PropertyOperator.NOT_IN.value
                else ast.CompareOperationOp.InCohort
            ),
            right=ast.Constant(value=cohort.pk),
        )

    # TODO: Add support for these types: "recording"

    raise NotImplementedError(
        f"property_to_expr not implemented for filter type {type(property).__name__} and {property.type}"
    )


def action_to_expr(action: Action, events_alias: Optional[str] = None) -> ast.Expr:
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


def entity_to_expr(entity: RetentionEntity, team: Team) -> ast.Expr:
    if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
        action = Action.objects.get(pk=entity.id)
        return action_to_expr(action)
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
        filters.append(property_to_expr(entity.properties, team))

    return ast.And(exprs=filters)


def tag_name_to_expr(tag_name: str):
    regex = rf"(^|;){tag_name}(\.|$|;|:)"
    expr = parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=str(regex))})
    return expr


def selector_to_expr(selector_string: str):
    selector = Selector(selector_string, escape_slashes=False)
    exprs = []
    regex = build_selector_regex(selector)
    exprs.append(parse_expr("elements_chain =~ {regex}", {"regex": ast.Constant(value=regex)}))

    useful_elements: list[ast.Expr] = []
    for part in selector.parts:
        if "tag_name" in part.data:
            if part.data["tag_name"] in Element.USEFUL_ELEMENTS:
                useful_elements.append(ast.Constant(value=part.data["tag_name"]))

        if "attr_id" in part.data:
            id_expr = parse_expr(
                "indexOf(elements_chain_ids, {value}) > 0", {"value": ast.Constant(value=part.data["attr_id"])}
            )
            if len(selector.parts) == 1 and len(part.data.keys()) == 1:
                # OPTIMIZATION: if there's only one selector part and that only filters on an ID, we don't need to also query elements_chain separately
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
    return get_from_dict_or_attr(property, "type")


def get_property_key(property):
    return get_from_dict_or_attr(property, "key")


def get_property_value(property):
    return get_from_dict_or_attr(property, "value")


def get_property_operator(property):
    return get_from_dict_or_attr(property, "operator")


def operator_is_negative(operator: PropertyOperator) -> bool:
    return operator in [
        PropertyOperator.IS_NOT,
        PropertyOperator.NOT_ICONTAINS,
        PropertyOperator.NOT_REGEX,
        PropertyOperator.IS_NOT_SET,
        PropertyOperator.NOT_BETWEEN,
        PropertyOperator.NOT_IN,
    ]
