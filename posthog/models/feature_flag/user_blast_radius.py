from typing import Optional, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyOperator

from posthog.clickhouse.client.connection import Workload
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team
from posthog.queries.base import relative_date_parse_for_feature_flag_matching


def replace_proxy_properties(team: Team, feature_flag_condition: dict):
    prop_groups = Filter(data=feature_flag_condition, team=team).property_groups

    for prop in prop_groups.flat:
        if prop.operator in ("is_date_before", "is_date_after"):
            relative_date = relative_date_parse_for_feature_flag_matching(str(prop.value))
            if relative_date:
                prop.value = relative_date.strftime("%Y-%m-%d %H:%M:%S")
        # Normalize property values to strings to match JSON-stored properties
        # This maintains compatibility with how properties are stored in ClickHouse
        # Skip special properties like $group_key which refer to columns, not JSON properties
        elif prop.type in ("person", "group") and prop.key != "$group_key" and isinstance(prop.value, list):
            # Convert all list values to strings for consistent type matching
            prop.value = [str(v) for v in prop.value]
        elif (
            prop.type in ("person", "group")
            and prop.key != "$group_key"
            and not isinstance(prop.value, str | list | dict | type(None))
        ):
            # Convert single non-string values to strings
            prop.value = str(prop.value)

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
        operator = prop.operator or "exact"
        value = prop.value

        if operator in (PropertyOperator.EXACT, "exact"):
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=value),
                )
            )
        elif operator in (PropertyOperator.IS_NOT, "is_not"):
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=value),
                )
            )
        elif operator in (PropertyOperator.IN_, "in"):
            # Convert all values to strings for group key comparison
            in_values_list = cast(list, value if isinstance(value, list) else [value])  # type: ignore[list-item]
            in_str_values: list[str] = [str(v) for v in in_values_list]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in in_str_values]),
                )
            )
        elif operator in (PropertyOperator.NOT_IN, "not_in"):
            # Convert all values to strings for group key comparison
            not_in_values_list = cast(list, value if isinstance(value, list) else [value])  # type: ignore[list-item]
            not_in_str_values: list[str] = [str(v) for v in not_in_values_list]
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in not_in_str_values]),
                )
            )
        elif operator in (PropertyOperator.ICONTAINS, "icontains"):
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator in (PropertyOperator.NOT_ICONTAINS, "not_icontains"):
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotILike,
                    left=ast.Field(chain=["groups", "key"]),
                    right=ast.Constant(value=f"%{value}%"),
                )
            )
        elif operator in (PropertyOperator.REGEX, "regex"):
            where_exprs.append(
                ast.Call(
                    name="match",
                    args=[
                        ast.Field(chain=["groups", "key"]),
                        ast.Constant(value=value),
                    ],
                )
            )
        elif operator in (PropertyOperator.NOT_REGEX, "not_regex"):
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
