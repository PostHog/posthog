from collections.abc import Iterable

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role


def enable_access_control(organization: Organization, *, role_based: bool = False) -> None:
    """Add the access control feature, and optionally role-based access, to the organization's features."""
    wanted = [AvailableFeature.ACCESS_CONTROL, *([AvailableFeature.ROLE_BASED_ACCESS] if role_based else [])]
    features = list(organization.available_product_features or [])
    present = {feature["key"] for feature in features}
    features += [{"key": key, "name": key} for key in wanted if key not in present]
    organization.available_product_features = features
    organization.save()


def restrict_project(
    team: Team,
    *,
    plain_members: Iterable[OrganizationMembership] = (),
    granted_members: Iterable[OrganizationMembership] = (),
    granted_roles: Iterable[Role] = (),
) -> None:
    """Make ``team`` a restricted project that only org admins and the granted members and roles can access.

    The features are saved on ``team.organization``, so refresh any other instance of that organization.
    Org admins and owners always keep access, so ``plain_members`` are set to member level first.
    """
    roles = list(granted_roles)
    enable_access_control(team.organization, role_based=bool(roles))
    for membership in plain_members:
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

    AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")
    for membership in granted_members:
        AccessControl.objects.create(
            team=team,
            resource="project",
            resource_id=str(team.id),
            organization_member=membership,
            access_level="member",
        )
    for role in roles:
        AccessControl.objects.create(
            team=team, resource="project", resource_id=str(team.id), role=role, access_level="member"
        )
