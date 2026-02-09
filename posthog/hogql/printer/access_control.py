from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.database.schema.system import SYSTEM_TABLE_TO_RESOURCE

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.postgres_table import PostgresTable


def get_blocked_resource_ids(resource: str, context: "HogQLContext") -> set[str]:
    """
    Get the set of resource IDs that should be blocked for this user.
    Uses the existing UserAccessControl logic to determine access.
    """
    from posthog.models import OrganizationMembership
    from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, UserAccessControl

    if not context.user or not context.team:
        return set()

    # Org admins see everything — no object-level filtering
    org_membership = OrganizationMembership.objects.filter(
        user=context.user, organization=context.team.organization
    ).first()
    if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
        return set()

    uac = UserAccessControl(user=context.user, team=context.team)

    # Get the access controls filters for this resource
    filters = uac._access_controls_filters_for_queryset(resource)
    access_controls = uac._get_access_controls(filters)

    blocked_resource_ids: set[str] = set()
    resource_id_access_levels: dict[str, list[str]] = {}

    for access_control in access_controls:
        if access_control.resource_id:
            resource_id_access_levels.setdefault(access_control.resource_id, []).append(access_control.access_level)

    for resource_id, access_levels in resource_id_access_levels.items():
        # Get the access controls for this specific resource_id to check role/member
        resource_access_controls = [ac for ac in access_controls if ac.resource_id == resource_id]

        # Only consider access controls that have explicit role or member (not defaults)
        explicit_access_controls = [
            ac for ac in resource_access_controls if ac.role is not None or ac.organization_member is not None
        ]

        if not explicit_access_controls:
            if all(access_level == NO_ACCESS_LEVEL for access_level in access_levels):
                blocked_resource_ids.add(resource_id)
            # No explicit controls for this object - don't block it
            continue

        # Check if user has any non-"none" access to this specific object
        has_specific_access = any(ac.access_level != NO_ACCESS_LEVEL for ac in explicit_access_controls)

        if not has_specific_access:
            # All explicit access levels are "none" - block this object
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
    resource = SYSTEM_TABLE_TO_RESOURCE.get(table.name)
    if not resource:
        return None  # Not access-controlled

    # Get blocked IDs for this resource
    blocked_ids = get_blocked_resource_ids(resource, context)

    if not blocked_ids:
        return None  # No blocked IDs, no filtering needed

    # Build: toString(id) NOT IN (blocked_ids)
    # We convert id to string because AccessControl stores resource_id as string
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="toString",
            args=[ast.Field(chain=["id"], type=ast.FieldType(name="id", table_type=table_type))],
        ),
        right=ast.Tuple(exprs=[ast.Constant(value=bid) for bid in blocked_ids]),
        type=ast.BooleanType(),
    )
