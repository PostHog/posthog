import json
from enum import Enum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional, cast, get_args

from django.contrib.auth.models import AnonymousUser
from django.db.models import Case, CharField, Exists, Model, OuterRef, Q, QuerySet, Value, When
from django.db.models.functions import Cast

from rest_framework import serializers

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.scopes import API_SCOPE_OBJECTS, APIScopeObject

if TYPE_CHECKING:
    from posthog.models.file_system.file_system import FileSystem

    from ee.models import AccessControl

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
AccessControlLevelResource = Literal[AccessControlLevelNone, "viewer", "editor", "manager"]
AccessControlLevel = Literal[AccessControlLevelMember, AccessControlLevelResource]

NO_ACCESS_LEVEL = "none"
ACCESS_CONTROL_LEVELS_MEMBER: tuple[AccessControlLevelMember, ...] = get_args(AccessControlLevelMember)
ACCESS_CONTROL_LEVELS_RESOURCE: tuple[AccessControlLevelResource, ...] = get_args(AccessControlLevelResource)

ACCESS_CONTROL_RESOURCES: tuple[APIScopeObject, ...] = (
    "action",
    "feature_flag",
    "dashboard",
    "insight",
    "notebook",
    "session_recording",
    "revenue_analytics",
    "survey",
    "experiment",
    "web_analytics",
)

# Resource inheritance mapping - child resources inherit access from parent resources
RESOURCE_INHERITANCE_MAP: dict[APIScopeObject, APIScopeObject] = {
    "session_recording_playlist": "session_recording",
}


class UserAccessControlError(Exception):
    resource: APIScopeObject
    required_level: AccessControlLevel
    resource_id: Optional[str]

    def __init__(self, resource: APIScopeObject, required_level: AccessControlLevel, resource_id: Optional[str] = None):
        super().__init__(
            f"Access control failure. You don't have `{required_level}` access to the `{resource}` resource."
        )
        self.resource = resource
        self.required_level = required_level
        self.resource_id = resource_id


def get_field_access_control_map(model_class: type[Model]) -> dict[str, tuple[APIScopeObject, AccessControlLevel]]:
    """
    Dynamically retrieve field-level access control requirements from model fields.
    This function looks for fields decorated with @requires_access.
    """
    field_access_map = {}

    # Iterate through all fields in the model
    for field in model_class._meta.get_fields():
        # Check if the field has access control metadata
        if hasattr(field, "_access_control_resource") and hasattr(field, "_access_control_level"):
            field_access_map[field.name] = (field._access_control_resource, field._access_control_level)

    return field_access_map


def resource_to_display_name(resource: APIScopeObject) -> str:
    """Convert resource name to human-readable display name"""
    # Handle special cases
    if resource == "organization":
        return "organization"  # singular

    # Default: replace underscores and add 's' for plural
    return f"{resource.replace('_', ' ')}s"


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


def minimum_access_level(resource: APIScopeObject) -> AccessControlLevel:
    """Returns the minimum allowed access level for a resource. 'none' is not included if a minimum is specified."""
    if resource == "action":
        return "viewer"
    return "none"


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
    if name == "sessionrecording":
        return "session_recording"
    if name == "sessionrecordingplaylist":
        return "session_recording_playlist"

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

    # ------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # Preloading access controls
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # Object level - checking conditions for specific items
    # ------------------------------------------------------------

    def access_level_for_object(
        self, obj: Model, resource: Optional[APIScopeObject] = None, explicit=False, specific_only=False
    ) -> Optional[AccessControlLevel]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value

        Args:
            obj: The model object to check access for
            resource: The resource type (auto-detected if not provided)
            explicit: If True, only return explicit access controls (no fallback to default)
            specific_only: If True, only consider access controls with roles or organization members
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

        # Filter to specific access controls if requested
        if specific_only:
            access_controls = [
                ac for ac in access_controls if ac.role is not None or ac.organization_member is not None
            ]
            # If we're looking for specific access controls and there are none we don't want to return the default access level
            if not access_controls:
                return None

        # If there is no specified controls on the resource then we return the default access level
        if not access_controls:
            return default_access_level(resource) if not explicit else None

        # If there are access controls we pick the highest level the user has
        return max(
            access_controls,
            key=lambda access_control: ordered_access_levels(resource).index(access_control.access_level),
        ).access_level

    def check_access_level_for_object(self, obj: Model, required_level: AccessControlLevel, explicit=False) -> bool:
        """
        Entry point for all permissions around a specific object.
        If any of the access controls have the same or higher level than the requested level, return True.

        Returns true or false if access controls are applied, otherwise None
        """

        resource = model_to_resource(obj)
        if not resource:
            # Permissions do not apply to models without a related scope
            return True

        access_level = self.get_user_access_level(obj, explicit=explicit)

        if not access_level:
            return False

        # If no access control exists
        return access_level_satisfied_for_resource(resource, access_level, required_level)

    def check_can_modify_access_levels_for_object(self, obj: Model) -> bool:
        """
        Special case for checking if the user can modify the access levels for an object.
        Unlike check_access_level_for_object, this requires that one of these conditions is true:
        1. The user is the creator of the object
        2. The user is explicitly a project admin
        3. The user is an org admin
        4. The user has "manager" access to the resource
        """

        if getattr(obj, "created_by", None) == self._user:
            # TODO: Should this always be the case, even for projects?
            return True

        # If they aren't the creator then they need to be a project admin, org admin, or have "manager" access to the resource
        # TRICKY: If self._team isn't set, this is likely called for a Team itself so we pass in the object
        resource = model_to_resource(obj)
        project_admin_check = self.check_access_level_for_object(
            self._team or obj, required_level="admin", explicit=True
        )

        # Only check for "manager" access if it's not a project resource
        if resource != "project":
            return project_admin_check or self.check_access_level_for_object(
                obj, required_level="manager", explicit=True
            )

        return project_admin_check

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

    # ------------------------------------------------------------
    # Object level (specific) - checking conditions for specific items with a member or role
    # ------------------------------------------------------------

    def specific_access_level_for_object(self, obj: Model, explicit=False) -> Optional[AccessControlLevel]:
        """
        This is different than access_level_for_object, it's only looking at access levels that have
        a role or member for the object. It will fallback to access_level_for_object if none is found.
        """
        return self.access_level_for_object(obj, explicit=explicit, specific_only=True)

    # ------------------------------------------------------------
    # Resource level - checking conditions for the resource type
    # ------------------------------------------------------------

    def access_level_for_resource(self, resource: APIScopeObject) -> Optional[AccessControlLevel]:
        """
        Access levels are strings - the order of which is determined at run time.
        We find all relevant access controls and then return the highest value
        """

        # Check if this resource inherits access from a parent resource
        parent_resource = RESOURCE_INHERITANCE_MAP.get(resource)
        if parent_resource:
            # Use parent resource for access control checks
            return self.access_level_for_resource(parent_resource)

        # These are resources which we don't have resource level access controls for
        if resource == "organization" or resource == "project" or resource == "plugin":
            return default_access_level(resource)

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

        # For inherited resources, use the parent resource's access levels for comparison
        comparison_resource = RESOURCE_INHERITANCE_MAP.get(resource, resource)

        if not access_level:
            return False

        return access_level_satisfied_for_resource(comparison_resource, access_level, required_level)

    def assert_access_level_for_resource(self, resource: APIScopeObject, required_level: AccessControlLevel) -> bool:
        """
        Stricter version of `check_access_level_for_resource`.
        Checks for specific object-level access as well as resource-level access.
        If they don't, raise a `UserAccessControlError`.
        """

        if not self.check_access_level_for_resource(resource, required_level):
            raise UserAccessControlError(resource, required_level)

        return True

    def has_any_specific_access_for_resource(
        self, resource: APIScopeObject, required_level: AccessControlLevel
    ) -> bool:
        """
        Check if the user has any object-level access controls for the given resource type
        that meet or exceed the required access level.

        This is useful when a user has "none" access at the resource level but may have
        specific grants to individual objects of that resource type.
        """
        org_membership = self._organization_membership

        if not resource or not org_membership:
            return False

        # Org admins always have access
        if org_membership.level >= OrganizationMembership.Level.ADMIN:
            return True

        # If access controls aren't supported, return False since we're looking for specific grants
        if not self.access_controls_supported:
            return False

        # Get all object-level access controls for this resource type
        filters = self._access_controls_filters_for_queryset(resource)
        access_controls = self._get_access_controls(filters)

        # These are already pre-loaded so filter what's in memory
        access_controls = [ac for ac in access_controls if ac.role is not None or ac.organization_member is not None]

        # Check if any access control meets the required level
        for access_control in access_controls:
            if access_level_satisfied_for_resource(resource, access_control.access_level, required_level):
                return True

        return False

    def effective_access_level_for_resource(self, resource: APIScopeObject) -> Optional[AccessControlLevel]:
        """
        Get the effective access level for a resource, considering both resource-level
        and specific object-level access.

        This is used for UI navigation decisions - it allows users to see resource pages
        if they have specific object access, but does NOT grant creation permissions.

        Returns:
        - The resource-level access if it's not "none"
        - "viewer" if user has specific object access (allows page access but not creation)
        - None or "none" if user has no access at all
        """
        # First check resource-level access
        resource_access = self.access_level_for_resource(resource)

        # If resource access is not "none", return it directly
        if resource_access and resource_access != NO_ACCESS_LEVEL:
            return resource_access

        # If resource access is "none" or None, check for specific object access
        # For navigation purposes, if they have specific access to any objects,
        # grant them "viewer" level to see the resource page but NOT create new items
        if self.has_any_specific_access_for_resource(resource, required_level="viewer"):
            return "viewer"

        return resource_access  # This will be "none" or None

    # ------------------------------------------------------------
    # Filtering querysets
    # ------------------------------------------------------------

    def filter_queryset_by_access_level(self, queryset: QuerySet, include_all_if_admin=False) -> QuerySet:
        # Filter queryset based on access controls, handling cases where user has "none" resource access
        # but may have specific object access

        model = cast(Model, queryset.model)
        resource = model_to_resource(model)

        if not resource:
            return queryset

        if include_all_if_admin:
            org_membership = self._organization_membership

            if org_membership and org_membership.level >= OrganizationMembership.Level.ADMIN:
                return queryset

        # Check if user has "none" access at resource level
        resource_access_level = self.access_level_for_resource(resource)
        has_resource_access = resource_access_level and resource_access_level != NO_ACCESS_LEVEL

        model_has_creator = hasattr(model, "created_by")

        filters = self._access_controls_filters_for_queryset(resource)
        access_controls = self._get_access_controls(filters)

        blocked_resource_ids: set[str] = set()
        allowed_resource_ids: set[str] = set()
        resource_id_access_levels: dict[str, list[str]] = {}

        for access_control in access_controls:
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

            if has_specific_access:
                allowed_resource_ids.add(resource_id)
            else:
                # All explicit access levels are "none" - block this object
                blocked_resource_ids.add(resource_id)

        # Apply filtering logic based on resource-level access
        if not has_resource_access and allowed_resource_ids:
            # User has "none" resource access but specific object access
            # Only show objects they have explicit access to (plus created objects)
            if model_has_creator:
                queryset = queryset.filter(Q(id__in=allowed_resource_ids) | Q(created_by=self._user))
            else:
                queryset = queryset.filter(id__in=allowed_resource_ids)
        elif blocked_resource_ids:
            # Standard case: exclude explicitly blocked objects
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

    # ------------------------------------------------------------
    # User access level
    # ------------------------------------------------------------

    def get_user_access_level(self, obj: Model, explicit=False) -> Optional[AccessControlLevel]:
        resource = model_to_resource(obj)
        specific_access_level_for_object = None
        access_level_for_resource = None

        # Check object specific access levels
        specific_access_level_for_object = self.specific_access_level_for_object(obj, explicit=explicit)

        if specific_access_level_for_object:
            return specific_access_level_for_object

        # Check resource access levels
        if resource and self.has_access_levels_for_resource(resource):
            access_level_for_resource = self.access_level_for_resource(resource)

        if access_level_for_resource:
            return access_level_for_resource

        # Check object general access levels
        access_level_for_object = self.access_level_for_object(obj, explicit=explicit)
        return access_level_for_object


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

        return self.user_access_control.get_user_access_level(obj)

    def validate(self, attrs):
        """
        Validate field-level access control for model updates.
        Only checks fields that are being modified and have access control requirements.
        """
        attrs = super().validate(attrs)

        # Only perform field access control validation for updates (not creates)
        if not self.instance:
            return attrs

        # Get field access control mappings for this model
        model_class = self.instance.__class__
        field_mappings = get_field_access_control_map(model_class)

        # If no field access controls are defined for this model, continue
        if not field_mappings:
            return attrs

        # Check access control for each field being modified
        user_access_control = self.user_access_control
        if not user_access_control:
            return attrs

        for field_name, _new_value in attrs.items():
            if field_name not in field_mappings:
                continue

            # Get the required resource and access level for this field
            resource, required_level = field_mappings[field_name]

            # Check if user has the required access level
            if not user_access_control.check_access_level_for_resource(resource, required_level):
                display_name = resource_to_display_name(resource)
                raise serializers.ValidationError(
                    {field_name: f"You need {required_level} access to {display_name} to modify this field."}
                )

        return attrs
