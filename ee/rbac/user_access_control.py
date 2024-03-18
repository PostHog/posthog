from rest_framework.permissions import BasePermission

from functools import cached_property
from django.db.models import Q, QuerySet
from typing import List, Optional

from ee.models.rbac.access_control import AccessControl
from posthog.models import (
    Organization,
    OrganizationMembership,
    Team,
    User,
)
from posthog.models.personal_api_key import APIScopeObject
from posthog.permissions import extract_organization

MEMBER_BASED_ACCESS_LEVELS = ["member", "admin"]
RESOURCE_BASED_ACCESS_LEVELS = ["viewer", "editor"]


def _get_access_level_order(resource: APIScopeObject) -> List[str]:
    if resource in ["project", "organization"]:
        return MEMBER_BASED_ACCESS_LEVELS

    return RESOURCE_BASED_ACCESS_LEVELS


def access_level_satisfied(resource: APIScopeObject, current_level: str, required_level: str) -> bool:
    return _get_access_level_order(resource).index(current_level) >= _get_access_level_order(resource).index(
        required_level
    )


class UserAccessControl:
    def __init__(self, user: User, organization: Optional[Organization] = None, team: Optional[Team] = None):
        self._user = user
        self._team = team
        self._organization = organization

    @cached_property
    def _organization_membership(self, organization: Organization) -> Optional[OrganizationMembership]:
        return OrganizationMembership.objects.get(organization=organization, user=self.user)

    # @cached_property
    def _access_controls_for_object(self, resource: APIScopeObject, resource_id: str) -> List[AccessControl]:
        """
        Used when checking an individual object - gets all access controls for the object and its type
        """
        # TODO: Make this more efficient
        role_memberships = self._user.role_memberships.select_related("role").all()
        role_ids = [membership.role.id for membership in role_memberships]

        # TODO: Need to determine if there exists any ACs for the resource to determine if we should return None or not
        return AccessControl.objects.filter(
            Q(  # Access controls applying to this user
                organization=self._organization,
                organization_member__user=self._user,
                resource=resource,
                resource_id=resource_id,
            )
            | Q(  # Access controls applying to this team
                organization=self._organization, team=self._team, resource=resource, resource_id=resource_id
            )
            | Q(  # Access controls applying to this user's roles
                organization=self._organization, role__in=role_ids, resource=resource, resource_id=resource_id
            )
        )

    def access_control_for_object(self, resource: APIScopeObject, resource_id: str) -> Optional[AccessControl]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        # TODO: Figure out - do we need also wan to include Resource level controls (i.e. where resource_id is explicitly None?)
        # or are they only applicable when there is no object level controls?

        # TODO: Override this based on your Org membership level

        access_controls = self._access_controls_for_object(resource, resource_id)
        if not access_controls:
            return

        return max(
            access_controls,
            key=lambda access_control: _get_access_level_order(resource).index(access_control.access_level),
        )

    def check_access_level_for_object(
        self, resource: APIScopeObject, resource_id: str, required_level: str
    ) -> Optional[bool]:
        """
        Entry point for all permissions around a specific object.
        If any of the access controls have the same or higher level than the requested level, return True.

        Returns true or false if access controls are applied, otherwise None
        """

        access_control = self.access_control_for_object(resource, resource_id)

        if not access_control:
            return

        return access_level_satisfied(resource, access_control.access_level, required_level)

    # Used for filtering a queryset by access level
    def filter_queryset_by_access_level(self, queryset: QuerySet) -> QuerySet:
        # TODO: Get list of all access controls for the user and then filter the queryset based on that
        # For now we just need to make sure this works for project filtering

        # 1. Check the overall setting for project access (to determine if we are filtering in or filtering out)
        # 2. Get all access controls for projects where the user has explicit access
        # 3. Filter the queryset based on the access controls

        # queryset = queryset.filter(
        #     id__in=(access_control.resource_id for access_control in access_controls_for_resource(user))
        # )

        return queryset


class AccessControlPermission(BasePermission):
    """
    Unified permissions access - controls access to any object based on the user's access controls
    """

    def _get_user_access_control(self, request, view) -> UserAccessControl:
        organization = extract_organization(object, view)
        try:
            # TODO: Check this is correct...
            if request.resolver_match.url_name.startswith("team-"):
                # /projects/ endpoint handling
                team = view.get_object()
            else:
                team = view.team
        except Team.DoesNotExist:
            pass

        return UserAccessControl(user=request.user, organization=organization, team=team)

    def has_object_permission(self, request, view, object) -> bool:
        # At this level we are checking an individual resource - this could be a project or a lower level item like a Dashboard
        uac = self._get_user_access_control(request, view)

        # TODO: How to determine action level to check...
        required_level = "viewer"
        has_access = uac.check_access_level_for_object(view.scope_object, str(object.id), required_level=required_level)

        if not has_access:
            self.message = f"You do not have {required_level} access to this resource."
            return False

        return True

    def has_permission(self, request, view) -> bool:
        # At this level we are checking that the user can generically access the resource kind.
        # Primarily we are checking the user's access to the parent resource type (i.e. project, organization)
        # as well as enforcing any global restrictions (e.g. generically only editing of a flag is allowed)

        uac = self._get_user_access_control(request, view)

        try:
            team = view.team
            is_member = uac.check_access_level_for_object("project", str(team.id), "member")

            if not is_member:
                self.message = f"You are not a member of this project."
                return False

        except (ValueError, KeyError):
            # TODO: Does this means its okay because there is no team level thing?
            pass
