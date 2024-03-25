from functools import cached_property
from django.db.models import Model, Q, QuerySet
from rest_framework import serializers
from typing import TYPE_CHECKING, List, Optional

from posthog.constants import AvailableFeature
from posthog.models import (
    Organization,
    OrganizationMembership,
    Team,
    User,
)
from posthog.models.scopes import APIScopeObject, API_SCOPE_OBJECTS


if TYPE_CHECKING:
    from ee.models import AccessControl

    _AccessControl = AccessControl
else:
    _AccessControl = object


try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


NO_ACCESS_LEVEL = "none"
MEMBER_BASED_ACCESS_LEVELS = [NO_ACCESS_LEVEL, "member", "admin"]
RESOURCE_BASED_ACCESS_LEVELS = [NO_ACCESS_LEVEL, "viewer", "editor"]


def ordered_access_levels(resource: APIScopeObject) -> List[str]:
    if resource in ["project", "organization"]:
        return MEMBER_BASED_ACCESS_LEVELS

    return RESOURCE_BASED_ACCESS_LEVELS


def default_access_level(resource: APIScopeObject) -> bool:
    if resource in ["project", "organization"]:
        return "member"
    return "editor"


def access_level_satisfied_for_resource(resource: APIScopeObject, current_level: str, required_level: str) -> bool:
    return ordered_access_levels(resource).index(current_level) >= ordered_access_levels(resource).index(required_level)


def model_to_resource(model: Model) -> Optional[APIScopeObject]:
    """
    Given a model, return the resource type it represents
    """
    if hasattr(model, "_meta"):
        name = model._meta.model_name
    else:
        name = model.__class__.__name__.lower()

    # NOTE: These are special mappings where the 1-1 of APIScopeObject doesn't match
    if name == "team":
        return "project"
    if name == "featureflag":
        return "feature_flag"

    if name not in API_SCOPE_OBJECTS:
        return None

    return name


class UserAccessControl:
    def __init__(self, user: User, team: Optional[Team] = None, organization: Optional[Organization] = None):
        self._user = user
        self._team = team
        self._organization: Organization = organization or team.organization

    @cached_property
    def _organization_membership(self) -> Optional[OrganizationMembership]:
        try:
            return OrganizationMembership.objects.get(organization=self._organization, user=self._user)
        except OrganizationMembership.DoesNotExist:
            return None

    @property
    def rbac_supported(self) -> bool:
        return self._organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

    @property
    def access_controls_supported(self) -> bool:
        # NOTE: This is a proxy feature. We may want to consider making it explicit later
        # ADVANCED_PERMISSIONS was only for dashboard collaborators, PROJECT_BASED_PERMISSIONING for project permissions
        # both now apply to this generic access control
        return self._organization.is_feature_available(
            AvailableFeature.PROJECT_BASED_PERMISSIONING
        ) or self._organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS)

    # @cached_property
    def _access_controls_for_object(self, obj: Model, resource: str) -> List[_AccessControl]:
        """
        Used when checking an individual object - gets all access controls for the object and its type
        """
        resource_id = str(obj.id)

        # TODO: Make this more efficient
        role_memberships = self._user.role_memberships.select_related("role").all()
        role_ids = [membership.role.id for membership in role_memberships] if self.rbac_supported else []

        # TODO: Need to determine if there exists any ACs for the resource to determine if we should return None or not
        return AccessControl.objects.filter(
            Q(  # Access controls applying to this team
                team=self._team, resource=resource, resource_id=resource_id, organization_member=None, role=None
            )
            | Q(  # Access controls applying to this user
                team=self._team,
                resource=resource,
                resource_id=resource_id,
                organization_member__user=self._user,
                role=None,
            )
            | Q(  # Access controls applying to this user's roles
                team=self._team, resource=resource, resource_id=resource_id, organization_member=None, role__in=role_ids
            )
        )

    # @cached_property
    def _access_controls_for_resource(self, resource: APIScopeObject) -> List[_AccessControl]:
        """
        Used when checking an individual object - gets all access controls for the object and its type
        """
        # TODO: Make this more efficient
        role_memberships = self._user.role_memberships.select_related("role").all()
        role_ids = [membership.role.id for membership in role_memberships] if self.rbac_supported else []

        return AccessControl.objects.filter(
            Q(  # Access controls applying to this team
                team=self._team, resource=resource, resource_id=None, organization_member=None, role=None
            )
            | Q(  # Access controls applying to this user
                team=self._team,
                resource=resource,
                resource_id=None,
                organization_member__user=self._user,
                role=None,
            )
            | Q(  # Access controls applying to this user's roles
                team=self._team, resource=resource, resource_id=None, organization_member=None, role__in=role_ids
            )
        )

    # Object level - checking conditions for specific items
    def access_control_for_object(self, obj: Model, resource: Optional[str] = None) -> Optional[_AccessControl]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        if not obj:
            return None

        resource = resource or model_to_resource(obj)
        if not resource:
            return None

        resource_id = str(obj.id)

        if not self.access_controls_supported:
            return None

        org_membership = self._organization_membership

        if not org_membership:
            # NOTE: Technically this is covered by Org Permission check so more of a sanity check
            return None

        # Org admins always have object level access
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return AccessControl(
                team=self._team,
                resource=resource,
                resource_id=resource_id,
                access_level=ordered_access_levels(resource)[-1],
            )

        access_controls = self._access_controls_for_object(obj, resource)
        if not access_controls:
            return AccessControl(
                team=self._team,
                resource=resource,
                resource_id=resource_id,
                access_level=default_access_level(resource),
            )

        return max(
            access_controls,
            key=lambda access_control: ordered_access_levels(resource).index(access_control.access_level),
        )

    def check_access_level_for_object(self, obj: Model, required_level: str) -> Optional[bool]:
        """
        Entry point for all permissions around a specific object.
        If any of the access controls have the same or higher level than the requested level, return True.

        Returns true or false if access controls are applied, otherwise None
        """

        resource = model_to_resource(obj)
        if not resource:
            return None

        access_control = self.access_control_for_object(obj, resource)

        return (
            False
            if not access_control
            else access_level_satisfied_for_resource(resource, access_control.access_level, required_level)
        )

    def check_can_modify_access_levels_for_object(self, obj: Model, resource: Optional[str] = None) -> Optional[bool]:
        """
        Special case for checking if the user can modify the access levels for an object.
        Unlike check_access_level_for_object, this requires that one of these conditions is true:
        1. The user is the creator of the object
        2. The user is a project admin
        2. The user is an org admin
        """

        if getattr(obj, "created_by", None) == self._user:
            # TODO: Should this always be the case, even for projects?
            return True

        # If they aren't the creator then they need to be a project admin or org admin
        # TRICKY: If self._team isn't set, this is likely called for a Team itself so we pass in the object
        return self.check_access_level_for_object(self._team or obj, required_level="admin")

    # Resource level - checking conditions for the resource type

    # Object level - checking conditions for specific items
    def access_control_for_resource(self, resource: APIScopeObject) -> Optional[_AccessControl]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        if not resource:
            return None

        if not self.access_controls_supported:
            return None

        org_membership = self._organization_membership

        if not org_membership:
            # NOTE: Technically this is covered by Org Permission check so more of a sanity check
            return None

        # Org admins always have object level access
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return AccessControl(
                team=self._team,
                resource=resource,
                resource_id=None,
                access_level=ordered_access_levels(resource)[-1],
            )

        access_controls = self._access_controls_for_resource(resource)
        if not access_controls:
            return AccessControl(
                team=self._team,
                resource=resource,
                resource_id=None,
                access_level=default_access_level(resource),
            )

        return max(
            access_controls,
            key=lambda access_control: ordered_access_levels(resource).index(access_control.access_level),
        )

    def check_access_level_for_resource(self, resource: APIScopeObject, required_level: str) -> Optional[bool]:
        access_control = self.access_control_for_resource(resource)

        return (
            False
            if not access_control
            else access_level_satisfied_for_resource(resource, access_control.access_level, required_level)
        )

    def filter_queryset_by_access_level(self, queryset: QuerySet, resource: Optional[str] = None) -> QuerySet:
        # Find all items related to the queryset model that have access controls such that the effective level for the user is "none"
        # and exclude them from the queryset

        model = queryset.model
        resource = resource or model_to_resource(model)

        if not resource:
            return queryset

        model_has_creator = hasattr(model, "created_by")

        # TODO: Make this more efficient
        role_memberships = self._user.role_memberships.select_related("role").all()
        role_ids = [membership.role.id for membership in role_memberships] if self.rbac_supported else []

        filter_args = dict(resource=resource, resource_id__isnull=False)

        if self._team and resource != "project":
            filter_args["team"] = self._team
        else:
            filter_args["team__organization"] = self._organization

        # With the resource, we can now filter for the access controls that apply to the user
        access_controls = AccessControl.objects.filter(
            Q(  # Access controls applying to this team for specific resources
                **filter_args, organization_member=None, role=None
            )
            | Q(  # Access controls applying to this user for specific resources
                **filter_args,
                organization_member__user=self._user,
                role=None,
            )
            | Q(  # Access controls applying to this user's roles
                **filter_args,
                organization_member=None,
                role__in=role_ids,
            )
        )

        blocked_resource_ids: set[str] = set()
        resource_id_access_levels: dict[str, list[str]] = {}

        for access_control in access_controls:
            resource_id_access_levels.setdefault(access_control.resource_id, []).append(access_control.access_level)

        for resource_id, access_levels in resource_id_access_levels.items():
            # Check if every access level is "none"
            if all(access_level == NO_ACCESS_LEVEL for access_level in access_levels):
                blocked_resource_ids.add(resource_id)

        # Filter the queryset based on the access controls
        if blocked_resource_ids:
            # Filter out any IDs where the user is not the creator and the id is blocked
            if model_has_creator:
                queryset = queryset.exclude(Q(id__in=blocked_resource_ids) & ~Q(created_by=self._user))
            else:
                queryset = queryset.exclude(id__in=blocked_resource_ids)

        return queryset


class UserAccessControlSerializerMixin(serializers.Serializer):
    user_access_level = serializers.SerializerMethodField(
        read_only=True,
        help_text="The effective access level the user has for this object",
    )

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        # NOTE: The user_access_control is typically on the view but in specific cases such as the posthog_app_context it is set at the context level
        if "user_access_control" in self.context:
            return self.context["user_access_control"]
        return self.context["view"].user_access_control

    def get_user_access_level(self, obj: Model) -> Optional[str]:
        access_control = self.user_access_control.access_control_for_object(obj)
        return access_control.access_level if access_control else None
