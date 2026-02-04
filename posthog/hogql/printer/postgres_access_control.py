"""
Access control filter generation for PostgreSQL queries.

This module provides functions to build HogQL AST expressions that enforce
access control when querying Django models via the postgres dialect.
"""

from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.database.schema.django_tables import DjangoTable

from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


def team_id_guard_for_postgres(
    table_type: ast.TableOrSelectType,
    context: "HogQLContext",
) -> ast.Expr:
    """
    Generate a team_id guard expression for PostgreSQL tables.

    This is similar to the ClickHouse team_id_guard_for_table but for PostgreSQL.
    """
    from posthog.hogql.errors import InternalHogQLError

    if not context.team_id:
        raise InternalHogQLError("context.team_id not found")

    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["team_id"], type=ast.FieldType(name="team_id", table_type=table_type)),
        right=ast.Constant(value=context.team_id),
        type=ast.BooleanType(),
    )


def build_access_control_filter(
    table: DjangoTable,
    table_type: ast.TableOrSelectType,
    context: "HogQLContext",
) -> Optional[ast.Expr]:
    """
    Build an access control filter expression for a Django table.

    This translates the UserAccessControl.filter_queryset_by_access_level logic
    into a HogQL AST expression.

    The logic is:
    1. If org admin, no filter needed (checked before query)
    2. If user is creator, they have access
    3. If user is not in blocked list, they have access

    Args:
        table: The DjangoTable being queried
        table_type: The AST type for the table
        context: The HogQL context with access control info

    Returns:
        An AST expression for the access control filter, or None if no filter needed
    """
    # If org admin, no filter needed
    if context.is_org_admin:
        return None

    # If no resource associated with this table, no access control
    if not table.resource or table.resource not in ACCESS_CONTROL_RESOURCES:
        return None

    # If no user context, we can't apply access control (shouldn't happen in practice)
    if not context.user_id:
        return None

    exprs: list[ast.Expr] = []

    # Creator bypass: created_by_id = user_id
    if table.has_created_by:
        creator_check = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["created_by_id"], type=ast.FieldType(name="created_by_id", table_type=table_type)),
            right=ast.Constant(value=context.user_id),
            type=ast.BooleanType(),
        )
        exprs.append(creator_check)

    # Build subquery to check if resource is NOT blocked
    # This checks the ee_accesscontrol table for explicit "none" access
    blocked_subquery = _build_blocked_ids_subquery(table.resource, context)
    if blocked_subquery:
        not_blocked_check = ast.CompareOperation(
            op=ast.CompareOperationOp.NotIn,
            # Cast id to text for comparison with resource_id (which is text)
            left=ast.Call(
                name="CAST",
                args=[
                    ast.Field(chain=["id"], type=ast.FieldType(name="id", table_type=table_type)),
                    ast.Constant(value="TEXT"),
                ],
            ),
            right=blocked_subquery,
            type=ast.BooleanType(),
        )
        exprs.append(not_blocked_check)

    if not exprs:
        return None

    # Combine with OR: creator_check OR not_blocked_check
    if len(exprs) == 1:
        return exprs[0]
    return ast.Or(exprs=exprs, type=ast.BooleanType())


def _build_blocked_ids_subquery(
    resource: str,
    context: "HogQLContext",
) -> Optional[ast.Expr]:
    """
    Build a subquery that returns IDs of resources that are explicitly blocked.

    The subquery selects from ee_accesscontrol where:
    - team_id matches
    - resource type matches
    - resource_id is not null (object-level access control)
    - access_level = 'none'
    - (organization_member_id = user's or role_id in user's roles)

    This is translated to SQL at print time.
    """
    if not context.team_id:
        return None

    # Build the member/role filter
    member_role_filters: list[ast.Expr] = []

    if context.organization_membership_id:
        member_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["organization_member_id"]),
            right=ast.Constant(value=context.organization_membership_id),
            type=ast.BooleanType(),
        )
        member_role_filters.append(member_filter)

    if context.role_ids:
        role_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["role_id"]),
            right=ast.Tuple(exprs=[ast.Constant(value=role_id) for role_id in context.role_ids]),
            type=ast.BooleanType(),
        )
        member_role_filters.append(role_filter)

    if not member_role_filters:
        # No user context to check against
        return None

    member_role_check = ast.Or(exprs=member_role_filters) if len(member_role_filters) > 1 else member_role_filters[0]

    # Build the complete WHERE clause
    where_exprs = [
        # team_id = context.team_id
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["team_id"]),
            right=ast.Constant(value=context.team_id),
            type=ast.BooleanType(),
        ),
        # resource = resource_name
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["resource"]),
            right=ast.Constant(value=resource),
            type=ast.BooleanType(),
        ),
        # resource_id IS NOT NULL
        ast.Call(
            name="isNotNull",
            args=[ast.Field(chain=["resource_id"])],
        ),
        # access_level = 'none'
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["access_level"]),
            right=ast.Constant(value="none"),
            type=ast.BooleanType(),
        ),
        # member/role check
        member_role_check,
    ]

    # Build the subquery
    subquery = ast.SelectQuery(
        select=[ast.Field(chain=["resource_id"])],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["ee_accesscontrol"]),
        ),
        where=ast.And(exprs=where_exprs),
    )

    return subquery
