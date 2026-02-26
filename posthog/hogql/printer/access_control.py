from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.postgres_table import PostgresTable

    from posthog.scopes import APIScopeObject


def get_blocked_resource_ids(resource: "APIScopeObject", context: "HogQLContext") -> set[str]:
    """
    Get the set of resource IDs that should be blocked for this user.
    Matches filter_queryset_by_access_level in rbac
    """
    from posthog.models import OrganizationMembership
    from posthog.rbac.user_access_control import NO_ACCESS_LEVEL

    if not context.database or not context.database.user_access_control:
        return set()

    uac = context.database.user_access_control

    # Org admins see everything
    org_membership = uac._organization_membership
    if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
        return set()

    # Get object-level access control entries
    filters = uac.access_controls_filters_for_queryset(resource)
    access_controls = uac.get_access_controls(filters)

    access_controls_by_resource_id: dict[str, list] = {}
    for access_control in access_controls:
        if access_control.resource_id:
            access_controls_by_resource_id.setdefault(access_control.resource_id, []).append(access_control)

    blocked_resource_ids: set[str] = set()
    for resource_id, resource_access_controls in access_controls_by_resource_id.items():
        explicit_access_controls = [
            ac for ac in resource_access_controls if ac.role is not None or ac.organization_member is not None
        ]

        if explicit_access_controls and all(ac.access_level == NO_ACCESS_LEVEL for ac in explicit_access_controls):
            blocked_resource_ids.add(resource_id)
        elif not explicit_access_controls and all(
            ac.access_level == NO_ACCESS_LEVEL for ac in resource_access_controls
        ):
            blocked_resource_ids.add(resource_id)

    return blocked_resource_ids


def build_access_control_guard(
    table: "PostgresTable",
    table_type: ast.TableOrSelectType,
    context: "HogQLContext",
) -> Optional[ast.Expr]:
    """
    Build access control WHERE clause for system tables.
    Returns None if no filtering needed.
    """
    resource = table.access_scope
    if not resource:
        return None

    pk = table.primary_key
    if pk is None:
        return None

    blocked_ids = get_blocked_resource_ids(resource, context)

    if not blocked_ids:
        return None

    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=[pk], type=ast.FieldType(name=pk, table_type=table_type))],
        ),
        right=ast.Tuple(exprs=[ast.Constant(value=bid) for bid in blocked_ids]),
        type=ast.BooleanType(),
    )
