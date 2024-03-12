from typing import Optional, Sequence
from django.db.models import Q
from ee.models.rbac.access_control import AccessControl
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from posthog.models.user import User


def access_controls_for_object(
    user: User,
    organization: Organization,
    resource: str,
    resource_id: str,
    team: Optional[Team] = None,
) -> Sequence[AccessControl]:
    return AccessControl.objects.filter(
        # Access controls applying to this user
        Q(organization=organization, organization_membership__user=user, resource=resource, resource_id=resource_id)
        # Access controls applying to this team
        | Q(organization=organization, team=team, resource=resource, resource_id=resource_id)
        # Access controls applying to this user's roles
        | Q(organization=organization, role__in=user.roles, resource=resource, resource_id=resource_id)
    )


def access_level_for_object(
    user: User,
    organization: Organization,
    resource: str,
    resource_id: str,
    team: Optional[Team] = None,
) -> list[str]:
    access_controls = access_controls_for_object(user, organization, resource, resource_id, team)

    return [access_control.access_level for access_control in access_controls]
