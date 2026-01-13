from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyOperator

from posthog.clickhouse.client.connection import Workload
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex, Property
from posthog.models.team.team import Team
from posthog.queries.base import relative_date_parse_for_feature_flag_matching


def _normalize_property_value(prop: Property) -> None:
    """
    Normalize property values to strings to match JSON-stored properties in ClickHouse.
    Skip special properties like $group_key which refer to columns, not JSON properties.
    """
    if prop.key == "$group_key":
        return  # Don't normalize $group_key - it's a column reference

    if prop.type in ("person", "group"):
        if isinstance(prop.value, list):
            prop.value = [str(v) for v in prop.value]
        elif not isinstance(prop.value, str | list | dict | type(None)):
            prop.value = str(prop.value)


def replace_proxy_properties(team: Team, feature_flag_condition: dict):
    prop_groups = Filter(data=feature_flag_condition, team=team).property_groups

    for prop in prop_groups.flat:
        if prop.operator in ("is_date_before", "is_date_after"):
            relative_date = relative_date_parse_for_feature_flag_matching(str(prop.value))
            if relative_date:
                prop.value = relative_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            _normalize_property_value(prop)

    return Filter(data={"properties": prop_groups.to_dict()}, team=team)


def get_user_blast_radius(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
):
    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

    if group_type_index is not None:
        return _get_group_blast_radius(team, cleaned_filter, group_type_index)
    else:
        return _get_person_blast_radius(team, cleaned_filter)


def _get_person_blast_radius(team: Team, filter: Filter) -> tuple[int, int]:
    """Calculate blast radius for person-based feature flags using HogQL."""
    from posthog.hogql.query import execute_hogql_query

    properties = filter.property_groups.flat

    if len(properties) == 0:
        # No filters means all persons are affected
        total_users = team.persons_seen_so_far
        return total_users, total_users

    # Build the SELECT query - property_to_expr handles all properties including cohorts
    select_query = _build_person_count_query(team, filter)

    # Execute the query
    response = execute_hogql_query(
        query=select_query,
        team=team,
    )

    total_count = response.results[0][0] if response.results else 0
    total_users = team.persons_seen_so_far
    blast_radius = min(total_count, total_users)

    return blast_radius, total_users


def _build_person_count_query(team: Team, filter: Filter):
    """Build HogQL AST query to count distinct persons matching filters."""
    from posthog.hogql import ast
    from posthog.hogql.property import property_to_expr

    # Build the main SELECT with count(DISTINCT persons.id)
    select_query = ast.SelectQuery(
        select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["persons", "id"])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
    )

    # Build WHERE clause with team_id and property filters
    # property_to_expr handles all property types including cohorts
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["persons", "team_id"]),
            right=ast.Constant(value=team.pk),
        )
    ]

    # Add all property filters (including cohorts) via property_to_expr
    property_expr = property_to_expr(filter.property_groups, team, scope="person")
    where_exprs.append(property_expr)

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    return select_query


def _get_group_blast_radius(team: Team, filter: Filter, group_type_index: GroupTypeIndex) -> tuple[int, int]:
    """Calculate blast radius for group-based feature flags using HogQL."""
    from posthog.hogql.query import execute_hogql_query

    properties = filter.property_groups.flat

    # Validate all group properties have correct group_type_index
    for property in properties:
        if property.key == "$group_key":
            # Special case: $group_key doesn't need a group_type_index as it refers to the key itself
            property.group_type_index = group_type_index
        elif property.group_type_index is None or property.group_type_index != group_type_index:
            raise ValidationError("Invalid group type index for feature flag condition.")

    if len(properties) == 0:
        # No filters means all groups of this type are affected
        total_groups = team.groups_seen_so_far(group_type_index)
        return total_groups, total_groups

    # Build the SELECT query for groups
    select_query = _build_group_count_query(team, filter, group_type_index)

    # Execute the query with OFFLINE workload (groups queries can be massive)
    response = execute_hogql_query(
        query=select_query,
        team=team,
        workload=Workload.OFFLINE,
    )

    total_affected = response.results[0][0] if response.results else 0
    total_groups = team.groups_seen_so_far(group_type_index)

    return total_affected, total_groups


def _build_group_count_query(team: Team, filter: Filter, group_type_index: GroupTypeIndex):
    """Build HogQL AST query to count distinct groups matching filters."""
    from posthog.hogql import ast
    from posthog.hogql.property import property_to_expr

    # Build the main SELECT with count(DISTINCT groups.key)
    select_query = ast.SelectQuery(
        select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["groups", "key"])])],
        select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
    )

    # Build WHERE clauses
    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["groups", "team_id"]),
            right=ast.Constant(value=team.pk),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["groups", "index"]),
            right=ast.Constant(value=group_type_index),
        ),
    ]

    # Handle $group_key properties specially - they reference the key column directly
    # Split properties into $group_key properties and regular properties
    group_key_properties = []
    regular_properties = []

    for prop in filter.property_groups.flat:
        if prop.key == "$group_key":
            group_key_properties.append(prop)
        else:
            regular_properties.append(prop)

    # Add $group_key filters directly as column comparisons
    for prop in group_key_properties:
        # Normalize operator to PropertyOperator enum for consistent comparisons
        operator = PropertyOperator(prop.operator) if prop.operator else PropertyOperator.EXACT
        value = prop.value

        # Convert values to strings for consistency (groups.key is a String column)
        # Handles both single values and lists, preserving None
        if isinstance(value, list):
            value = [str(v) if v is not None else None for v in value]
        elif value is not None:
            value = str(value)

        if operator == PropertyOperator.EXACT:
            if isinstance(value, list):
                # List values should use IN logic (match any value in the list)
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                    )
                )
            else:
                # Single value uses equality
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Constant(value=value),
                    )
                )
        elif operator == PropertyOperator.IS_NOT:
            if isinstance(value, list):
                # List values should use NOT IN logic (doesn't match any value)
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotIn,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                    )
                )
            else:
                # Single value uses inequality
                where_exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Field(chain=["groups", "key"]),
                        right=ast.Constant(value=value),
                    )
                )
        elif operator == PropertyOperator.IN_:
            values_list = value if isinstance(value, list) else [value]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values_list]),
                )
            )
        elif operator == PropertyOperator.NOT_IN:
            values_list = value if isinstance(value, list) else [value]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in values_list]),
                )
            )
        elif operator == PropertyOperator.ICONTAINS:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'icontains' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator == PropertyOperator.NOT_ICONTAINS:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'not_icontains' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator == PropertyOperator.REGEX:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'regex' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.Call(
                    name="match",
                    args=[
                        ast.Field(chain=["groups", "key"]),
                        ast.Constant(value=value),
                    ],
                )
            )
        elif operator == PropertyOperator.NOT_REGEX:
            if isinstance(value, list):
                raise ValidationError(
                    "Operator 'not_regex' does not support list values for $group_key property. "
                    "Use a single value instead."
                )
            where_exprs.append(
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(
                            name="match",
                            args=[
                                ast.Field(chain=["groups", "key"]),
                                ast.Constant(value=value),
                            ],
                        )
                    ],
                )
            )
        else:
            # Unsupported operator for $group_key
            raise ValidationError(
                f"Operator '{operator}' is not supported for $group_key property. "
                f"Supported operators: exact, is_not, in, not_in, icontains, not_icontains, regex, not_regex"
            )

    # Add regular property filters using property_to_expr (only if there are any)
    if regular_properties:
        from posthog.models.property import PropertyGroup

        regular_filter = Filter(
            data={"properties": PropertyGroup(type=filter.property_groups.type, values=regular_properties).to_dict()},
            team=team,
        )
        property_expr = property_to_expr(regular_filter.property_groups, team, scope="group")
        where_exprs.append(property_expr)

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    return select_query
