from uuid import UUID

from django.db.models import Q

from products.access_control.backend.facade.contracts import AuthorizationRole, AuthorizationRule
from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role


def authorization_rules(team_id: int, organization_id: UUID) -> tuple[AuthorizationRule, ...]:
    rows = AccessControl.objects.filter(
        Q(resource_id__isnull=True) | Q(resource__in=["project", "dashboard", "insight"]),
        team_id=team_id,
        resource__in=["project", *ACCESS_CONTROL_RESOURCES],
    ).select_related("organization_member", "role")
    return tuple(
        AuthorizationRule(
            resource=row.resource,
            resource_id=row.resource_id,
            access_level=row.access_level,
            organization_member_id=row.organization_member_id,
            role_id=row.role_id,
        )
        for row in rows
        if (row.organization_member is None or row.organization_member.organization_id == organization_id)
        and (row.role is None or row.role.organization_id == organization_id)
        and not (row.organization_member_id is not None and row.role_id is not None)
    )


def authorization_roles(organization_id: UUID) -> tuple[AuthorizationRole, ...]:
    return tuple(
        AuthorizationRole(
            id=role.id,
            user_ids=tuple(role.roles.valid_for_authorization().values_list("user_id", flat=True)),
        )
        for role in Role.objects.filter(organization_id=organization_id)
    )
