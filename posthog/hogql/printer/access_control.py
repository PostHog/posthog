from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.database.schema.system import SYSTEM_TABLE_TO_RESOURCE

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.postgres_table import PostgresTable


def get_blocked_resource_ids(resource: str, context: "HogQLContext") -> set[str]:
    """
    Get the set of resource IDs that should be blocked for this user.
    Highest access level from object default, role, or member entries applies.
    """
    from posthog.models import OrganizationMembership
    from posthog.rbac.user_access_control import NO_ACCESS_LEVEL

    if not context.database or not context.database._user_access_control:
        return set()

    uac = context.database._user_access_control

    # Org admins see everything
    org_membership = uac._organization_membership
    if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
        return set()

    # Get object-level access control entries
    filters = uac._access_controls_filters_for_queryset(resource)
    access_controls = uac._get_access_controls(filters)

    # Block resource_ids where the highest access is "none"
    access_by_id: dict[str, list[str]] = {}
    for ac in access_controls:
        if ac.resource_id:
            access_by_id.setdefault(ac.resource_id, []).append(ac.access_level)

    return {
        resource_id for resource_id, levels in access_by_id.items() if all(level == NO_ACCESS_LEVEL for level in levels)
    }


def build_access_control_guard(
    table: "PostgresTable",
    table_type: ast.TableOrSelectType,
    context: "HogQLContext",
) -> Optional[ast.Expr]:
    """
    Build access control WHERE clause for system tables.
    Returns None if no filtering needed.
    """
    resource = SYSTEM_TABLE_TO_RESOURCE.get(table.name)
    if not resource:
        return None

    blocked_ids = get_blocked_resource_ids(resource, context)

    if not blocked_ids:
        return None

    # Example: `toString(id) NOT IN (id_1, id_2, ...)`
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=["id"], type=ast.FieldType(name="id", table_type=table_type))],
        ),
        right=ast.Tuple(exprs=[ast.Constant(value=bid) for bid in blocked_ids]),
        type=ast.BooleanType(),
    )
