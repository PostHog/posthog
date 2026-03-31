import logging
from dataclasses import dataclass
from typing import Optional

from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyOperator

from posthog.clickhouse.client.connection import Workload
from posthog.models.filters import Filter
from posthog.models.property import GroupTypeIndex, Property, PropertyGroup
from posthog.models.team.team import Team
from posthog.queries.base import relative_date_parse_for_feature_flag_matching

logger = logging.getLogger(__name__)


@dataclass
class BlastRadiusResult:
    users_affected: int
    total_users: int
    groups_affected: Optional[int] = None
    total_groups: Optional[int] = None
    users_query_error: Optional[str] = None
    groups_query_error: Optional[str] = None


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


def _split_properties_by_type(
    properties: list[Property],
) -> tuple[list[Property], list[Property]]:
    """Partition properties into person-type and group-type lists.

    Returns (person_properties, group_properties). The $group_key property
    is classified as group-type since it references the groups.key column.
    """
    person_props: list[Property] = []
    group_props: list[Property] = []
    for prop in properties:
        if prop.type == "group" or prop.key == "$group_key":
            group_props.append(prop)
        else:
            person_props.append(prop)
    return person_props, group_props


def _get_mixed_blast_radius(team: Team, filter: Filter, group_type_index: GroupTypeIndex) -> BlastRadiusResult:
    """Calculate blast radius when a condition has both person and group properties.

    Runs two independent queries — one against the persons table and one against
    the groups table — and returns both counts. The counts are independent
    estimates, which is acceptable since blast radius is already an approximation.

    If one sub-query fails, the other's results are still returned alongside an
    error message for the failed query, rather than failing the entire request.
    """
    all_properties = filter.property_groups.flat
    person_props, group_props = _split_properties_by_type(all_properties)

    # Person sub-query
    users_affected: int = 0
    total_users: int = team.persons_seen_so_far
    users_query_error: Optional[str] = None
    if person_props:
        try:
            person_filter = Filter(
                data={"properties": PropertyGroup(type=filter.property_groups.type, values=person_props).to_dict()},
                team=team,
            )
            users_affected, total_users = _get_person_blast_radius(team, person_filter)
        except Exception as e:
            logger.warning("Mixed blast radius: person sub-query failed", exc_info=True, extra={"team_id": team.pk})
            users_query_error = str(e)
    else:
        users_affected = total_users

    # Group sub-query
    groups_affected: Optional[int] = None
    total_groups: Optional[int] = None
    groups_query_error: Optional[str] = None
    if group_props:
        try:
            group_filter = Filter(
                data={"properties": PropertyGroup(type=filter.property_groups.type, values=group_props).to_dict()},
                team=team,
            )
            groups_affected, total_groups = _get_group_blast_radius(team, group_filter, group_type_index)
        except Exception as e:
            logger.warning("Mixed blast radius: group sub-query failed", exc_info=True, extra={"team_id": team.pk})
            groups_query_error = str(e)

    return BlastRadiusResult(
        users_affected=users_affected,
        total_users=total_users,
        groups_affected=groups_affected,
        total_groups=total_groups,
        users_query_error=users_query_error,
        groups_query_error=groups_query_error,
    )


def get_user_blast_radius(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
) -> BlastRadiusResult:
    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

    if group_type_index is not None:
        all_properties = cleaned_filter.property_groups.flat
        person_props, group_props = _split_properties_by_type(all_properties)

        if person_props and group_props:
            return _get_mixed_blast_radius(team, cleaned_filter, group_type_index)
        elif person_props:
            # Pure person properties with group aggregation (the common case today)
            affected, total = _get_person_blast_radius(team, cleaned_filter)
            return BlastRadiusResult(users_affected=affected, total_users=total)
        else:
            # Pure group properties, or no properties at all — delegate to the
            # group path which handles the "all groups" case for empty filters.
            affected, total = _get_group_blast_radius(team, cleaned_filter, group_type_index)
            return BlastRadiusResult(users_affected=affected, total_users=total)
    else:
        affected, total = _get_person_blast_radius(team, cleaned_filter)
        return BlastRadiusResult(users_affected=affected, total_users=total)


def get_user_blast_radius_persons(
    team: Team,
    feature_flag_condition: dict,
    group_type_index: Optional[GroupTypeIndex] = None,
    cursor: Optional[str] = None,
):
    # No rollout % calculations here, since it makes more sense to compute that on the frontend
    cleaned_filter = replace_proxy_properties(team, feature_flag_condition)

    if group_type_index is not None:
        return _get_group_blast_radius_persons(team, cleaned_filter, group_type_index, cursor=cursor)
    else:
        return _get_person_blast_radius_persons(team, cleaned_filter, cursor=cursor)


def _get_person_blast_radius(team: Team, filter: Filter) -> tuple[int, int]:
    """Calculate blast radius for person-based feature flags using HogQL."""
    from posthog.hogql.query import execute_hogql_query

    properties = filter.property_groups.flat

    if len(properties) == 0:
        # No filters means all persons are affected
        total_users = team.persons_seen_so_far
        return total_users, total_users

    # Build the SELECT query - property_to_expr handles all properties including cohorts
    select_query = _build_person_query(team, filter, return_count=True)

    # Execute the query
    response = execute_hogql_query(
        query=select_query,
        team=team,
    )

    total_count = response.results[0][0] if response.results else 0
    total_users = team.persons_seen_so_far
    blast_radius = min(total_count, total_users)

    return blast_radius, total_users


def _build_person_query(team: Team, filter: Filter, return_count: bool = True, cursor: Optional[str] = None):
    """Build HogQL AST query to count or select distinct persons matching filters."""
    from posthog.hogql import ast
    from posthog.hogql.property import property_to_expr

    # Build the main SELECT with either count(DISTINCT persons.id) or DISTINCT persons.id
    if return_count:
        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["persons", "id"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        )
    else:
        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["persons", "id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            distinct=True,
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

    # Add cursor-based pagination when returning IDs
    if not return_count and cursor is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["persons", "id"]),
                right=ast.Constant(value=cursor),
            )
        )

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    # Add ORDER BY and LIMIT for pagination when returning IDs
    if not return_count:
        select_query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["persons", "id"]), order="ASC")]
        select_query.limit = ast.Constant(value=500)

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
    select_query = _build_group_query(team, filter, group_type_index, return_count=True)

    # Execute the query with OFFLINE workload (groups queries can be massive)
    response = execute_hogql_query(
        query=select_query,
        team=team,
        workload=Workload.OFFLINE,
    )

    total_affected = response.results[0][0] if response.results else 0
    total_groups = team.groups_seen_so_far(group_type_index)

    return total_affected, total_groups


PERSON_BATCH_SIZE = 500


def _build_group_query(
    team: Team,
    filter: Filter,
    group_type_index: GroupTypeIndex,
    return_count: bool = True,
    cursor: Optional[str] = None,
):
    """Build HogQL AST query to count or select distinct groups matching filters."""
    from posthog.hogql import ast
    from posthog.hogql.property import property_to_expr

    # Build the main SELECT with either count(DISTINCT groups.key) or DISTINCT groups.key
    if return_count:
        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", distinct=True, args=[ast.Field(chain=["groups", "key"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        )
    else:
        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["groups", "key"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
            distinct=True,
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
                    "Operator 'regex' does not support list values for $group_key property. Use a single value instead."
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
        regular_filter = Filter(
            data={"properties": PropertyGroup(type=filter.property_groups.type, values=regular_properties).to_dict()},
            team=team,
        )
        property_expr = property_to_expr(regular_filter.property_groups, team, scope="group")
        where_exprs.append(property_expr)

    # Add cursor-based pagination when returning keys
    if not return_count and cursor is not None:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Field(chain=["groups", "key"]),
                right=ast.Constant(value=cursor),
            )
        )

    # Combine all WHERE expressions with AND
    select_query.where = ast.And(exprs=where_exprs)

    # Add ORDER BY and LIMIT for pagination when returning keys
    if not return_count:
        select_query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["groups", "key"]), order="ASC")]
        select_query.limit = ast.Constant(value=PERSON_BATCH_SIZE)

    return select_query


def _get_person_blast_radius_persons(team: Team, filter: Filter, cursor: Optional[str] = None) -> list[str]:
    """Get distinct person IDs matching person-based feature flag filters."""
    from posthog.hogql.query import execute_hogql_query

    # Build the SELECT query to get person IDs
    select_query = _build_person_query(team, filter, return_count=False, cursor=cursor)

    response = execute_hogql_query(
        query=select_query,
        team=team,
    )

    # Extract person IDs from results
    person_ids = [str(row[0]) for row in response.results] if response.results else []
    return person_ids


def _get_group_blast_radius_persons(
    team: Team, filter: Filter, group_type_index: GroupTypeIndex, cursor: Optional[str] = None
) -> list[str]:
    """Get distinct group keys matching group-based feature flag filters."""
    from posthog.hogql.query import execute_hogql_query

    properties = filter.property_groups.flat

    # Validate all group properties have correct group_type_index
    for property in properties:
        if property.key == "$group_key":
            property.group_type_index = group_type_index
        elif property.group_type_index is None or property.group_type_index != group_type_index:
            raise ValidationError("Invalid group type index for feature flag condition.")

    # Build the SELECT query to get group keys
    select_query = _build_group_query(team, filter, group_type_index, return_count=False, cursor=cursor)

    response = execute_hogql_query(
        query=select_query,
        team=team,
        workload=Workload.OFFLINE,
    )

    # Extract group keys from results
    group_keys = [str(row[0]) for row in response.results] if response.results else []
    return group_keys
