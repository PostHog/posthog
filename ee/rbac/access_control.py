from typing import Optional, Sequence
from django.db.models import Q, QuerySet
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


def access_controls_for_resource(
    user: User,
    organization: Organization,
    resource: str,
    team: Optional[Team] = None,
) -> Sequence[AccessControl]:
    return AccessControl.objects.filter(
        # Access controls applying to this user
        Q(organization=organization, organization_membership__user=user, resource=resource, resource_id=None)
        # Access controls applying to this team
        | Q(organization=organization, team=team, resource=resource, resource_id=None)
        # Access controls applying to this user's roles
        | Q(organization=organization, role__in=user.roles, resource=resource, resource_id=None)
    )


def filter_queryset_by_access_level(user: User, queryset: QuerySet) -> QuerySet:
    """
    For a given resource there is a bunch of things we need to check...
    1. Specific access - all resource_ids that the user, role or team can explicitly access should be included
    2. Generic access - all resources that the user, role or team can access should be included
    """
    pass

    # First get the general rule for view level access - this decides if we are filtering out or filtering in
    # TODO: Does this mean we need to standardize access levels?

    # If the default for the org / project / role is no access then we need to filter in all things that the user has explicit access to

    # Otherwise we need to filter out all resource_ids that have at least one associated access control that the user does not have access to
    explicit_access_ids = []
