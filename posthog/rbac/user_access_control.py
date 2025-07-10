from functools import cached_property
import json
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q, OuterRef, Case, When, Value, Model, QuerySet, Exists, CharField
from django.db.models.functions import Cast
from rest_framework import serializers
from typing import TYPE_CHECKING, Any, Literal, Optional, cast, get_args
from enum import Enum

from posthog.constants import AvailableFeature
from posthog.models import (
    Organization,
    OrganizationMembership,
    Team,
    User,
)
from posthog.scopes import APIScopeObject, API_SCOPE_OBJECTS


if TYPE_CHECKING:
    from ee.models import AccessControl
    from posthog.models.file_system.file_system import FileSystem

    _AccessControl = AccessControl
else:
    _AccessControl = object


try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class AccessSource(Enum):
    """Enum for how a user got access to a resource"""

    CREATOR = "creator"
    ORGANIZATION_ADMIN = "organization_admin"
    EXPLICIT_MEMBER = "explicit_member"
    EXPLICIT_ROLE = "explicit_role"
    PROJECT_ADMIN = "project_admin"
    DEFAULT = "default"


AccessControlLevelNone = Literal["none"]
AccessControlLevelMember = Literal[AccessControlLevelNone, "member", "admin"]
AccessControlLevelResource = Literal[AccessControlLevelNone, "viewer", "editor"]
AccessControlLevel = Literal[AccessControlLevelMember, AccessControlLevelResource]

NO_ACCESS_LEVEL = "none"
ACCESS_CONTROL_LEVELS_MEMBER: tuple[AccessControlLevelMember, ...] = get_args(AccessControlLevelMember)
ACCESS_CONTROL_LEVELS_RESOURCE: tuple[AccessControlLevelResource, ...] = get_args(AccessControlLevelResource)

ACCESS_CONTROL_RESOURCES: tuple[APIScopeObject, ...] = (
    "feature_flag",
    "dashboard",
    "insight",
    "notebook",
)


def ordered_access_levels(resource: APIScopeObject) -> list[AccessControlLevel]:
    if resource in ["project", "organization"]:
        return list(ACCESS_CONTROL_LEVELS_MEMBER)

    return list(ACCESS_CONTROL_LEVELS_RESOURCE)


def default_access_level(resource: APIScopeObject) -> AccessControlLevel:
    if resource in ["project"]:
        return "admin"
    if resource in ["organization"]:
        return "member"
    return "editor"


def highest_access_level(resource: APIScopeObject) -> AccessControlLevel:
    return ordered_access_levels(resource)[-1]


def access_level_satisfied_for_resource(
    resource: APIScopeObject, current_level: AccessControlLevel, required_level: AccessControlLevel
) -> bool:
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
    if name == "plugin_config":
        return "plugin"

    if name not in API_SCOPE_OBJECTS:
        return None

    return cast(APIScopeObject, name)


class UserAccessControl:
    """
    UserAccessControl provides functions for checking unified access to all resources and objects from a Project level downwards.
    Typically a Team (Project) is required other than in certain circumstances, particularly when validating which projects a user has access to within an organization.
    """

    def __init__(self, user: User, team: Optional[Team] = None, organization_id: Optional[str] = None):
        self._user = user
        self._team = team
        self._cache: dict[str, list[AccessControl]] = {}

        if not organization_id and team:
            organization_id = str(team.organization_id)

        self._organization_id = organization_id

    def _clear_cache(self):
        self._cache = {}
        if hasattr(self, "_cached_access_controls"):
            delattr(self, "_cached_access_controls")
        if hasattr(self, "_organization_membership"):
            delattr(self, "_organization_membership")
        if hasattr(self, "_user_role_ids"):
            delattr(self, "_user_role_ids")

    @cached_property
    def _organization_membership(self) -> Optional[OrganizationMembership]:
        # NOTE: This is optimized to reduce queries - we get the users membership _with_ the organization
        try:
            if not self._organization_id:
                return None
            return OrganizationMembership.objects.select_related("organization").get(
                organization_id=self._organization_id, user=self._user
            )
        except OrganizationMembership.DoesNotExist:
            return None

    @cached_property
    def _organization(self) -> Optional[Organization]:
        if self._organization_membership:
            return self._organization_membership.organization
        return None

    @cached_property
    def _user_role_ids(self):
        if not self.rbac_supported:
            # Early return to prevent an unnecessary lookup
            return []

        role_memberships = cast(Any, self._user).role_memberships.select_related("role").all()
        return [membership.role.id for membership in role_memberships]

    @property
    def rbac_supported(self) -> bool:
        if not self._organization:
            return False

        return self._organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

    @property
    def access_controls_supported(self) -> bool:
        if not self._organization:
            return False

        return self._organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS)

    def _filter_options(self, filters: dict[str, Any]) -> Q:
        """
        Adds the 3 main filter options to the query
        """
        return (
            Q(  # Access controls applying to this team
                **filters, organization_member=None, role=None
            )
            | Q(  # Access controls applying to this user
                **filters, organization_member__user=self._user, role=None
            )
            | Q(  # Access controls applying to this user's roles
                **filters, organization_member=None, role__in=self._user_role_ids
            )
        )

    def _get_access_controls(self, filters: dict) -> list[_AccessControl]:
        key = json.dumps(filters, sort_keys=True)
        if key not in self._cache:
            self._cache[key] = list(AccessControl.objects.filter(self._filter_options(filters)))

        return self._cache[key]

    def _access_controls_filters_for_object(self, resource: APIScopeObject, resource_id: str) -> dict:
        """
        Used when checking an individual object - gets all access controls for the object and its type
        """
        # Plugins are a special case because they don't belong to a team, instead they belong to an organization
        if resource == "plugin":
            return {
                "team__organization_id": str(self._organization_id),
                "resource": resource,
                "resource_id": resource_id,
            }

        return {"team_id": self._team.id, "resource": resource, "resource_id": resource_id}  # type: ignore

    def _access_controls_filters_for_resource(self, resource: APIScopeObject) -> dict:
        """
        Used when checking overall access to a resource
        """

        return {"team_id": self._team.id, "resource": resource, "resource_id": None}  # type: ignore

    def _access_controls_filters_for_queryset(self, resource: APIScopeObject) -> dict:
        """
        Used to filter out IDs from a queryset based on access controls where the specific resource is denied access
        """
        common_filters: dict[str, Any] = {"resource": resource, "resource_id__isnull": False}

        if self._team and resource != "project":
            common_filters["team_id"] = self._team.id
        elif self._organization_id:
            common_filters["team__organization_id"] = str(self._organization_id)

        return common_filters

    def _fill_filters_cache(self, filter_groups: list[dict], access_controls: list[_AccessControl]) -> None:
        for filters in filter_groups:
            key = json.dumps(filters, sort_keys=True)

            # TRICKY: We have to simulate the entire DB query here:
            matching_access_controls = []

            for ac in access_controls:
                matches = True
                for key, value in filters.items():
                    if key == "resource_id__isnull":
                        if (ac.resource_id is None) != value:
                            matches = False
                            break
                    elif key == "team__organization_id":
                        if ac.team.organization_id != value:
                            matches = False
                            break
                    elif getattr(ac, key) != value:
                        matches = False
                        break
                if matches:
                    matching_access_controls.append(ac)

            self._cache[key] = matching_access_controls

    def preload_object_access_controls(self, objects: list[Model]) -> None:
        """
        Preload access controls for a list of objects
        """

        filter_groups: list[dict] = []

        for obj in objects:
            resource = model_to_resource(obj)
            if not resource:
                return

            filter_groups.append(self._access_controls_filters_for_object(resource, str(obj.id)))  # type: ignore

        q = Q()
        for filters in filter_groups:
            q = q | self._filter_options(filters)

        access_controls = list(AccessControl.objects.filter(q))
        self._fill_filters_cache(filter_groups, access_controls)

    def preload_access_levels(self, team: Team, resource: APIScopeObject, resource_id: Optional[str] = None) -> None:
        """
        Checking permissions can involve multiple queries to AccessControl e.g. project level, global resource level, and object level
        As we can know this upfront, we can optimize this by loading all the controls we will need upfront.
        """
        # Question - are we fundamentally loading every access control for the given resource? If so should we accept that fact and just load them all?
        # doing all additional filtering in memory?

        filter_groups: list[dict] = []

        filter_groups.append(self._access_controls_filters_for_object(resource="project", resource_id=str(team.id)))
        filter_groups.append(self._access_controls_filters_for_resource(resource))

        if resource_id:
            filter_groups.append(self._access_controls_filters_for_object(resource, resource_id=resource_id))
        else:
            filter_groups.append(self._access_controls_filters_for_queryset(resource))

        q = Q()
        for filters in filter_groups:
            q = q | self._filter_options(filters)

        access_controls = list(AccessControl.objects.filter(q))
        self._fill_filters_cache(filter_groups, access_controls)

    # Object level - checking conditions for specific items
    def access_level_for_object(
        self, obj: Model, resource: Optional[APIScopeObject] = None, explicit=False
    ) -> Optional[AccessControlLevel]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        resource = resource or model_to_resource(obj)
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return None

        # Creators always have highest access
        if getattr(obj, "created_by", None) == self._user:
            return highest_access_level(resource)

        # Org admins always have highest access
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return highest_access_level(resource)

        if resource == "organization":
            # Organization access is controlled via membership level only
            if org_membership.level >= OrganizationMembership.Level.ADMIN:
                return "admin"
            return "member"

        # If access controls aren't supported, then we return the default access level
        if not self.access_controls_supported:
            return default_access_level(resource) if not explicit else None

        filters = self._access_controls_filters_for_object(resource, str(obj.id))  # type: ignore
        access_controls = self._get_access_controls(filters)

        # If there is no specified controls on the resource then we return the default access level
        if not access_controls:
            return default_access_level(resource) if not explicit else None

        # If there are access controls we pick the highest level the user has
        return max(
            access_controls,
            key=lambda access_control: ordered_access_levels(resource).index(access_control.access_level),
        ).access_level

    def check_access_level_for_object(
        self, obj: Model, required_level: AccessControlLevel, explicit=False
    ) -> Optional[bool]:
        """
        Entry point for all permissions around a specific object.
        If any of the access controls have the same or higher level than the requested level, return True.

        Returns true or false if access controls are applied, otherwise None
        """

        resource = model_to_resource(obj)
        if not resource:
            # Permissions do not apply to models without a related scope
            return True

        access_level = self.access_level_for_object(obj, resource, explicit=explicit)

        if not access_level:
            return False

        # If no access control exists
        return access_level_satisfied_for_resource(resource, access_level, required_level)

    def check_can_modify_access_levels_for_object(self, obj: Model) -> Optional[bool]:
        """
        Special case for checking if the user can modify the access levels for an object.
        Unlike check_access_level_for_object, this requires that one of these conditions is true:
        1. The user is the creator of the object
        2. The user is explicitly a project admin
        2. The user is an org admin
        """

        if getattr(obj, "created_by", None) == self._user:
            # TODO: Should this always be the case, even for projects?
            return True

        # If they aren't the creator then they need to be a project admin or org admin
        # TRICKY: If self._team isn't set, this is likely called for a Team itself so we pass in the object
        return self.check_access_level_for_object(self._team or obj, required_level="admin", explicit=True)

    def get_access_source_for_object(
        self, obj: Model, resource: Optional[APIScopeObject] = None
    ) -> Optional[AccessSource]:
        """
        Determine how the user got access to an object.
        Returns None if the user has no access context.
        """
        resource = resource or model_to_resource(obj)
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return None

        # Check if user is the creator
        if getattr(obj, "created_by", None) == self._user:
            return AccessSource.CREATOR

        # Check if user is org admin
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return AccessSource.ORGANIZATION_ADMIN

        # If access controls aren't supported, return default
        if not self.access_controls_supported:
            return AccessSource.DEFAULT

        # Get cached access controls for this object
        filters = self._access_controls_filters_for_object(resource, str(obj.id))  # type: ignore
        cached_controls = self._get_access_controls(filters)

        # Check for explicit member access
        if any(ac.organization_member_id == org_membership.id for ac in cached_controls):
            return AccessSource.EXPLICIT_MEMBER

        # Check for explicit role access
        if any(ac.role_id in self._user_role_ids for ac in cached_controls if ac.role_id):
            return AccessSource.EXPLICIT_ROLE

        # Check for project-level access
        if self._team is None:
            return AccessSource.DEFAULT

        project_filters = self._access_controls_filters_for_object("project", str(self._team.id))
        project_access_controls = self._get_access_controls(project_filters)
        if any(
            ac.resource_id == str(self._team.id) and ac.organization_member_id == org_membership.id
            for ac in project_access_controls
        ):
            return AccessSource.PROJECT_ADMIN

        # Default access
        return AccessSource.DEFAULT

    # Resource level - checking conditions for the resource type
    def access_level_for_resource(self, resource: APIScopeObject) -> Optional[AccessControlLevel]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        org_membership = self._organization_membership

        if not resource or not org_membership:
            # In any of these cases, we can't determine the access level
            return None

        # Org admins always have resource level access
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return highest_access_level(resource)

        if not self.access_controls_supported:
            # If access controls aren't supported, then return the default access level
            return default_access_level(resource)

        filters = self._access_controls_filters_for_resource(resource)
        access_controls = self._get_access_controls(filters)

        if not access_controls:
            return default_access_level(resource)

        return max(
            access_controls,
            key=lambda access_control: ordered_access_levels(resource).index(access_control.access_level),
        ).access_level

    def has_access_levels_for_resource(self, resource: APIScopeObject) -> bool:
        if not self._team:
            # If there is no team, then there can't be any access controls on this resource
            return False

        filters = self._access_controls_filters_for_resource(resource)
        access_controls = self._get_access_controls(filters)
        return bool(access_controls)

    def check_access_level_for_resource(self, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
        access_level = self.access_level_for_resource(resource)

        if not access_level:
            return False

        return access_level_satisfied_for_resource(resource, access_level, required_level)

    def filter_queryset_by_access_level(self, queryset: QuerySet, include_all_if_admin=False) -> QuerySet:
        # Find all items related to the queryset model that have access controls such that the effective level for the user is "none"
        # and exclude them from the queryset

        model = cast(Model, queryset.model)
        resource = model_to_resource(model)

        if not resource:
            return queryset

        if include_all_if_admin:
            org_membership = self._organization_membership

            if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
                return queryset

        model_has_creator = hasattr(model, "created_by")

        filters = self._access_controls_filters_for_queryset(resource)
        access_controls = self._get_access_controls(filters)

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

    def filter_and_annotate_file_system_queryset(self, queryset: QuerySet["FileSystem"]) -> QuerySet["FileSystem"]:
        """
        Annotate each FileSystem with the effective_access_level (either 'none' or 'some')
        and exclude items that end up with 'none', unless the user is the creator or project-admin or org-admin/staff.
        """
        user = self._user
        org_membership = self._organization_membership

        # 1) If the user is staff or org-admin, they can see everything
        if user.is_staff or (org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN):
            return queryset

        # Subquery to check if user has "admin" on the FileSystem's team/project
        is_admin_for_project_subquery = (
            AccessControl.objects.filter(
                team_id=OuterRef("team_id"),
                resource="project",
                resource_id=Cast(OuterRef("team_id"), CharField()),
            )
            .filter(
                Q(organization_member__user=user)
                | Q(role__in=self._user_role_ids)
                | Q(organization_member=None, role=None)
            )
            .filter(access_level="admin")
            .values("pk")[:1]
        )

        # Subquery to check whether the user has "none" for this specific FileSystem
        is_none_subquery = (
            AccessControl.objects.filter(
                team_id=OuterRef("team_id"),
                resource=OuterRef("type"),
                resource_id=OuterRef("ref"),
            )
            .filter(
                Q(organization_member__user=user)
                | Q(role__in=self._user_role_ids)
                | Q(organization_member=None, role=None)
            )
            .filter(access_level="none")
            .values("pk")[:1]
        )

        # 2) Annotate the project-admin check + the is_none check
        queryset = queryset.annotate(
            is_project_admin=Exists(is_admin_for_project_subquery),
            is_none_access=Exists(is_none_subquery),
        )

        # 3) Compute effective_access_level:
        #
        #    - If is_none_access is True => "none"
        #    - Else => "some" ("editor" or "viewer")
        queryset = queryset.annotate(
            effective_access_level=Case(
                When(is_none_access=True, then=Value("none")),
                default=Value("some"),
                output_field=CharField(),
            )
        )

        # 4) Exclude items that are "none" if the user is not the creator,
        #    not a project admin, and not an org-admin/staff (already handled in step #1).
        queryset = queryset.exclude(Q(effective_access_level="none") & Q(is_project_admin=False) & ~Q(created_by=user))

        return queryset


class UserAccessControlSerializerMixin(serializers.Serializer):
    """
    Mixin for serializers to add user access control fields
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._preloaded_access_controls = False

    user_access_level = serializers.SerializerMethodField(
        read_only=True,
        help_text="The effective access level the user has for this object",
    )

    @property
    def user_access_control(self) -> Optional[UserAccessControl]:
        # NOTE: The user_access_control is typically on the view but in specific cases,
        # such as rendering HTML (`render_template()`), it is set at the context level
        if "user_access_control" in self.context:
            # Get it directly from the context
            return self.context["user_access_control"]
        elif hasattr(self.context.get("view", None), "user_access_control"):
            # Otherwise from the view (the default case)
            return self.context["view"].user_access_control
        elif "request" in self.context:
            user = cast(User | AnonymousUser, self.context["request"].user)
            # The user could be anonymous - if so there is no access control to be used

            if user.is_anonymous:
                return None

            user = cast(User, user)

            return UserAccessControl(user, organization_id=str(user.current_organization_id))

        return None

    def get_user_access_level(self, obj: Model) -> Optional[str]:
        if not self.user_access_control:
            return None

        # Check if self.instance is a list - if so we want to preload the user access controls
        if not self._preloaded_access_controls and isinstance(self.instance, list):
            self.user_access_control.preload_object_access_controls(self.instance)
            self._preloaded_access_controls = True

        resource = model_to_resource(obj)
        access_level_for_resource = None
        if resource and self.user_access_control.has_access_levels_for_resource(resource):
            access_level_for_resource = self.user_access_control.access_level_for_resource(resource)

        if access_level_for_resource:
            return access_level_for_resource

        access_level_for_object = self.user_access_control.access_level_for_object(obj)
        return access_level_for_object
