from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, cast

from django.apps import apps
from django.db.models import Q
from django.urls import URLResolver, get_resolver

from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE,
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
    RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS,
    AccessControlLevel,
    AccessSource,
    UserAccessControl,
    default_access_level,
    get_effective_access_level_for_member,
    get_effective_access_level_for_role,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, APIScopeObject, APIScopeObjectOrNotSupported

from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


class OrganizationMemberField(serializers.PrimaryKeyRelatedField):
    def __init__(self, **kwargs):
        kwargs.setdefault(
            "pk_field",
            serializers.UUIDField(
                format="hex_verbose",
                error_messages={
                    "invalid": "Invalid organization member id. "
                    "Use the 'id' field from the /api/organizations/<organization_id>/members/ endpoint.",
                },
            ),
        )
        super().__init__(**kwargs)


class UserAccessInfoSerializer(serializers.Serializer):
    """Serializer for user access information"""

    user_id = serializers.UUIDField()
    access_level = serializers.CharField()
    access_source = serializers.CharField(
        help_text="How the user got access: 'explicit_member', 'explicit_role', 'organization_admin', 'project_admin', 'creator', 'default'"
    )
    organization_membership_id = serializers.UUIDField(allow_null=True)
    organization_membership_level = serializers.CharField(allow_null=True)


class AccessControlSerializer(serializers.ModelSerializer):
    access_level = serializers.CharField(allow_null=True)

    class Meta:
        model = AccessControl
        fields = [
            "access_level",
            "resource",
            "resource_id",
            "organization_member",
            "role",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def build_relational_field(self, field_name, relation_info):
        """Override to customize error messages for organization_member field"""
        field_class, field_kwargs = super().build_relational_field(field_name, relation_info)

        if field_name == "organization_member":
            # Inject our custom field class with better error messages
            field_class = OrganizationMemberField

        return field_class, field_kwargs

    def validate_resource(self, resource):
        if resource not in API_SCOPE_OBJECTS or resource in INTERNAL_API_SCOPE_OBJECTS:
            allowed = tuple(s for s in API_SCOPE_OBJECTS if s not in INTERNAL_API_SCOPE_OBJECTS)
            raise serializers.ValidationError("Invalid resource. Must be one of: {}".format(allowed))

        return resource

    # Validate that access control is a valid option
    def validate_access_level(self, access_level):
        resource = self.initial_data["resource"]
        levels = ordered_access_levels(resource)

        if access_level and access_level not in levels:
            raise serializers.ValidationError(f"Invalid access level. Must be one of: {', '.join(levels)}")

        if access_level:
            min_level = minimum_access_level(resource)
            if levels.index(access_level) < levels.index(min_level):
                raise serializers.ValidationError(
                    f"Access level cannot be set below the minimum '{min_level}' for {resource}."
                )

            max_level = highest_access_level(resource)
            if levels.index(access_level) > levels.index(max_level):
                raise serializers.ValidationError(
                    f"Access level cannot be set above the maximum '{max_level}' for {resource}."
                )

        return access_level

    def validate(self, data):
        context = self.context

        # Ensure that only one of organization_member or role is set
        if data.get("organization_member") and data.get("role"):
            raise serializers.ValidationError("You can not scope an access control to both a member and a role.")

        access_control = cast(UserAccessControl, self.context["view"].user_access_control)
        resource = data["resource"]
        resource_id = data.get("resource_id")

        # We assume the highest level is required for the given resource to edit access controls
        required_level = highest_access_level(resource)
        team = context["view"].team
        the_object = context["view"].get_object()

        # Role-backed access controls require the ROLE_BASED_ACCESS feature — same gate
        # as the UI's "Roles" blocks and the runtime enforcement in UserTeamPermissions.
        if data.get("role") and not team.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS):
            raise exceptions.PermissionDenied("Role-based access controls require the Role-based access feature.")

        if resource_id:
            if str(the_object.pk) != str(resource_id):
                raise exceptions.PermissionDenied(
                    "Cannot modify access controls for a resource different from the URL target."
                )

            # Check that they have the right access level for this specific resource object
            if not access_control.check_can_modify_access_levels_for_object(the_object):
                raise exceptions.PermissionDenied(f"Must be {required_level} to modify {resource} permissions.")

            # Cap distinct objects with per-object overrides.
            # Only run the count when adding a rule for a previously-unrestricted object.
            if (
                data.get("access_level") is not None
                and not AccessControl.objects.filter(team=team, resource=resource, resource_id=resource_id).exists()
            ):
                distinct_objects = (
                    AccessControl.objects.filter(
                        team=team,
                        resource=resource,
                        resource_id__isnull=False,
                    )
                    .values("resource_id")
                    .distinct()
                    .count()
                )
                if distinct_objects >= ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE:
                    raise serializers.ValidationError(
                        f"Reached the limit of {ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE} {resource}s "
                        f"with access control overrides."
                    )
        else:
            # If modifying the base resource rules then we are checking the parent membership (project or organization)
            # NOTE: Currently we only support org level in the UI so its simply an org level check
            if not access_control.check_can_modify_access_levels_for_object(team):
                raise exceptions.PermissionDenied("Must be an Organization admin to modify project-wide permissions.")

        return data


@dataclass(frozen=True, kw_only=True)
class _ResourceDisplayModel:
    app_label: str
    model_name: str
    name_field: str


# Used only by _resolve_object_names below, which turns a rule's resource_id into a display name.
# Names come from universal search's ENTITY_MAP first; these entries cover resources search doesn't
# index, so they have no ENTITY_MAP entry to borrow. Add one when a resource's rules render raw ids
# instead of names; delete one when search starts indexing the resource, since ENTITY_MAP is
# consulted first and the entry goes dead. Resources in neither place fall back to the raw id.
_MODELS_NOT_IN_ENTITY_MAP: dict[str, _ResourceDisplayModel] = {
    "warehouse_view": _ResourceDisplayModel(
        app_label="data_modeling", model_name="datawarehousesavedquery", name_field="name"
    ),
    "warehouse_table": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="datawarehousetable", name_field="name"
    ),
    "external_data_source": _ResourceDisplayModel(
        app_label="warehouse_sources", model_name="externaldatasource", name_field="source_type"
    ),
    "session_recording": _ResourceDisplayModel(
        app_label="posthog", model_name="sessionrecording", name_field="session_id"
    ),
}


@dataclass(frozen=True, kw_only=True)
class _ResolvedObjectName:
    name: str | None
    # Insights link by short_id rather than pk, so the frontend needs it alongside the name
    short_id: str | None = None


def _resolve_object_names(resource: str, resource_ids: list[str], team_id: int) -> dict[str, _ResolvedObjectName]:
    """Map {resource_id -> display info} for one resource type. Best-effort: on any failure returns {}.

    Models and display fields come from universal search's ENTITY_MAP, whose keys match
    access-control resources, with a small supplement for resources search doesn't index.

    Queries through _base_manager so rules pointing at soft-deleted objects still resolve —
    those are exactly the rows someone opens this page to clean up. Tenant isolation holds
    via the explicit team_id filter.
    """
    from posthog.api.search import (
        ENTITY_MAP,  # noqa: PLC0415 — imports every searchable product model, keep it off this module's import path
    )

    if not resource_ids:
        return {}
    entity = ENTITY_MAP.get(resource)
    if entity is not None:
        model = entity["klass"]
        # The primary display field is the one search ranks highest (name / key / title)
        name_field = next((field for field, rank in entity["search_fields"].items() if rank == "A"), None)
        if name_field is None:
            return {}
        try:
            qs = model._base_manager.filter(team_id=team_id, pk__in=resource_ids)
            if resource == "insight":
                # Insight.name is nullable and saved insights often carry only derived_name
                return {
                    str(pk): _ResolvedObjectName(name=name or derived_name, short_id=short_id)
                    for pk, name, derived_name, short_id in qs.values_list("pk", "name", "derived_name", "short_id")
                }
            return {str(pk): _ResolvedObjectName(name=name) for pk, name in qs.values_list("pk", name_field)}
        except Exception as e:
            # The rules list falls back to raw ids, but report the error: it likely affects the whole resource type
            capture_exception(e, {"resource": resource})
            return {}
    registry = _MODELS_NOT_IN_ENTITY_MAP.get(resource)
    if not registry:
        return {}
    try:
        model = apps.get_model(registry.app_label, registry.model_name)
        rows = model._base_manager.filter(team_id=team_id, pk__in=resource_ids).values_list("pk", registry.name_field)
        return {str(pk): _ResolvedObjectName(name=name) for pk, name in rows}
    except Exception as e:
        # Type mismatch on pk (e.g. non-numeric id for an int pk), missing model, or missing team_id column
        capture_exception(e, {"resource": resource})
        return {}


# Project-level access is its own control (the "Project access" dropdown), never an object rule —
# every rules endpoint filters resource="project" out as well
_OBJECT_RULE_EXCLUDED_SCOPES: frozenset[str] = frozenset({"project"})


@cache
def resources_with_object_access_controls() -> frozenset[APIScopeObject]:
    """Resources whose viewsets expose per-object access controls, derived from the registered routes.

    A viewset opts into object-level access control by mixing in AccessControlViewSetMixin, so the
    routes are the source of truth and this set cannot drift from the code. The snapshot test in
    test_access_control.py makes additions show up in review.
    """
    found: set[APIScopeObject] = set()

    def walk(resolver: URLResolver) -> None:
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern)
                continue
            cls = getattr(pattern.callback, "cls", None)
            if cls is None or not issubclass(cls, AccessControlViewSetMixin):
                continue
            scope = getattr(cls, "scope_object", None)
            if (
                scope
                and scope != "INTERNAL"
                and scope not in INTERNAL_API_SCOPE_OBJECTS
                and scope not in _OBJECT_RULE_EXCLUDED_SCOPES
            ):
                found.add(scope)

    walk(get_resolver())
    return frozenset(found)


class AccessControlViewSetMixin(_GenericViewSet):
    # Why a mixin? We want to easily add this to any existing resource, including providing easy helpers for adding access control info such
    # as the current users access level to any response.
    # This mixin does:
    #    1. Adds an "access_controls" action to the viewset that handles access control for the given resource.
    #    2. Adds user access control information to list responses without modifying the pagination behavior.

    # We decided to go with the resource access level in the context of the app instead but we're
    # keeping this here in case it would be helpful in the future.
    # def get_paginated_response_with_access_control(self, data):
    #     """
    #     Returns a paginated response with user access level for the resource added.
    #     """
    #     response = self.get_paginated_response(data)

    #     resource_type = getattr(self, "scope_object", None)
    #     if resource_type and hasattr(self, "user_access_control"):
    #         response_data = {
    #             **response.data,
    #             "user_access_level": self.user_access_control.access_level_for_resource(resource_type),
    #         }
    #         return Response(response_data)

    #     return response

    # def get_list_response_with_access_control(self, queryset):
    #     page = self.paginate_queryset(queryset)
    #     if page is not None:
    #         serializer = self.get_serializer(page, many=True)
    #         return self.get_paginated_response_with_access_control(serializer.data)

    #     serializer = self.get_serializer(queryset, many=True)
    #     return Response(serializer.data)

    # def list(self, request, *args, **kwargs):
    #     """
    #     Note: this overrides the default list method to add user access control information to the response. If you
    #     need to override this method, you can call "get_list_response_with_access_control" directly in your
    #     own implementation of the list method.
    #     """
    #     queryset = self.filter_queryset(self.get_queryset())
    #     return self.get_list_response_with_access_control(queryset)

    # 1. Know that the project level access is covered by the Permission check
    # 2. Get the actual object which we can pass to the serializer to check if the user created it
    # 3. We can also use the serializer to check the access level for the object

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        """
        Dynamically determine required scopes based on HTTP method and action.
        GET requests to access control endpoints require 'access_control:read' scope.
        PUT requests have no additional scope requirements.
        """
        if request.method == "GET" and self.action in [
            "access_controls",
            "resource_access_controls",
            "global_access_controls",  # DEPRECATED - use resource_access_controls instead.
            "users_with_access",
            "access_control_defaults",
            "access_control_roles",
            "access_control_members",
            "access_control_default_objects",
            "access_control_default_properties",
            "access_control_member_objects",
            "access_control_member_properties",
            "access_control_role_objects",
            "access_control_role_properties",
        ]:
            return ["access_control:read"]
        elif request.method == "PUT" and self.action in [
            "access_controls",
            "resource_access_controls",
            "global_access_controls",  # DEPRECATED - use resource_access_controls instead.
        ]:
            return ["access_control:write"]

        return None

    def _get_access_control_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())
        return AccessControlSerializer(*args, **kwargs)

    def _get_access_controls(self, request: Request, is_resource_level=False):
        resource = cast(APIScopeObjectOrNotSupported, getattr(self, "scope_object", None))
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore
        team = cast(Team, self.team)  # type: ignore

        if not resource:
            raise exceptions.NotFound("Access controls are not available for this resource type.")

        if resource == "INTERNAL":
            raise exceptions.NotFound("Access controls are not available for internal resources.")

        if is_resource_level and resource != "project":
            raise exceptions.ValidationError("Resource-level access controls can only be configured for projects.")

        obj = self.get_object()
        resource_id = obj.id

        if is_resource_level:
            # If resource level then we are getting all controls for the project that aren't specific to a resource
            access_controls = AccessControl.objects.filter(team=team, resource_id=None).all()
        else:
            # Otherwise we are getting all controls for the specific resource
            access_controls = AccessControl.objects.filter(team=team, resource=resource, resource_id=resource_id).all()

        serializer = self._get_access_control_serializer(instance=access_controls, many=True)
        user_access_level = user_access_control.get_user_access_level(obj)

        payload: dict[str, Any] = {
            "access_controls": serializer.data,
            # NOTE: For resource level based controls we are always configuring resource level items
            "available_access_levels": ACCESS_CONTROL_LEVELS_RESOURCE
            if is_resource_level
            else ordered_access_levels(resource),
            "default_access_level": "editor" if is_resource_level else default_access_level(resource),
            "minimum_access_level": minimum_access_level(resource) if not is_resource_level else "none",
            "maximum_access_level": highest_access_level(resource) if not is_resource_level else "manager",
            "user_access_level": user_access_level,
            "user_can_edit_access_levels": user_access_control.check_can_modify_access_levels_for_object(obj),
        }

        if not is_resource_level:
            # The level this object falls back to when it carries no default of its own, so the UI
            # can spell out what removing the override means. Follows RESOURCE_INHERITANCE_MAP
            # because that's the resource the runtime check consults — a warehouse view is gated by
            # the warehouse_objects rules, not by its own.
            #
            # None for a project is load-bearing: it is what stops the UI offering "No override" on
            # a project's own default, which has nothing above it to fall back to. "No override"
            # belongs to object defaults only — project-level access is configured in its own
            # panel, which has no inherited tier to fall back to.
            inherited_resource = (
                None
                if resource in RESOURCES_WITHOUT_RESOURCE_LEVEL_CONTROLS
                else RESOURCE_INHERITANCE_MAP.get(resource, resource)
            )
            payload["inherited_resource"] = inherited_resource
            payload["inherited_access_level"] = None
            if inherited_resource:
                everyone_rule = AccessControl.objects.filter(
                    team=team,
                    resource=inherited_resource,
                    resource_id=None,
                    organization_member=None,
                    role=None,
                ).first()
                payload["inherited_access_level"] = (
                    everyone_rule.access_level if everyone_rule else default_access_level(inherited_resource)
                )

        return Response(payload)

    def _get_users_with_access(self, request: Request):
        """
        Get all users with access to the resource, including explicit and implicit access.
        """
        resource = cast(APIScopeObjectOrNotSupported, getattr(self, "scope_object", None))
        team = cast(Team, self.team)  # type: ignore

        if not resource or resource == "INTERNAL":
            raise exceptions.NotFound("User access information is not available for this resource.")

        obj = self.get_object()

        org_memberships = (
            OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
            .select_related("user")
            .prefetch_related("role_memberships__role")
        )

        users_with_access = []

        for membership in org_memberships:
            user = membership.user
            user_uac = UserAccessControl(user=user, team=team)

            # Check if user has access to the project first
            project_access = user_uac.check_access_level_for_object(team, required_level="member")
            if not project_access:
                continue

            access_level = user_uac.get_user_access_level(obj)
            if access_level is None or access_level == "none":
                continue

            access_source = user_uac.get_access_source_for_object(obj, resource) or AccessSource.DEFAULT

            users_with_access.append(
                {
                    "user_id": user.uuid,
                    "access_level": access_level,
                    "access_source": access_source.value,
                    "organization_membership_id": membership.id,
                    "organization_membership_level": OrganizationMembership.Level(membership.level).name.lower(),
                }
            )

        # Sort by access level (highest first) then by email
        access_levels = ordered_access_levels(resource)
        users_with_access.sort(key=lambda x: (access_levels.index(x["access_level"]), x["user_id"]), reverse=True)

        serializer = UserAccessInfoSerializer(users_with_access, many=True)
        return Response(
            {
                "users": serializer.data,
                "total_count": len(users_with_access),
            }
        )

    def _update_access_controls(self, request: Request, is_resource_level=False):
        resource = cast(APIScopeObjectOrNotSupported, getattr(self, "scope_object", None))

        if not resource:
            raise exceptions.NotFound("Access controls are not available for this resource type.")

        if resource == "INTERNAL":
            raise exceptions.NotFound("Access controls are not available for internal resources.")

        if is_resource_level and resource != "project":
            raise exceptions.ValidationError("Resource-level access controls can only be configured for projects.")

        obj = self.get_object()
        resource_id = str(obj.id)
        team = cast(Team, self.team)  # type: ignore

        # Generically validate the incoming data
        if not is_resource_level:
            # If not resource based we are deriving from the viewset
            data = request.data
            data["resource"] = resource
            data["resource_id"] = resource_id

        partial_serializer = self._get_access_control_serializer(data=request.data)
        partial_serializer.is_valid(raise_exception=True)
        params = partial_serializer.validated_data

        instance = AccessControl.objects.filter(
            team=team,
            resource=params["resource"],
            resource_id=params.get("resource_id"),
            organization_member=params.get("organization_member"),
            role=params.get("role"),
        ).first()

        if params["access_level"] is None:
            if instance:
                instance.delete()
                # Drop the preloaded access-control snapshot so later reads this request are fresh.
                self.user_access_control._clear_cache()  # type: ignore[attr-defined]
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Perform the upsert
        if instance:
            serializer = self._get_access_control_serializer(instance, data=request.data)
        else:
            serializer = self._get_access_control_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        serializer.validated_data["team"] = team
        serializer.save()
        # Drop the preloaded access-control snapshot so later reads this request are fresh.
        self.user_access_control._clear_cache()  # type: ignore[attr-defined]

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(exclude=True)
    @action(methods=["GET", "PUT"], detail=True)
    def access_controls(self, request: Request, *args, **kwargs):
        """
        Get or update access controls for the resource.
        """
        if request.method == "PUT":
            return self._update_access_controls(request)

        return self._get_access_controls(request)

    @extend_schema(exclude=True)
    @action(methods=["GET", "PUT"], detail=True)
    def resource_access_controls(self, request: Request, *args, **kwargs):
        """
        Get or update resource access controls for the project.
        """
        if request.method == "PUT":
            return self._update_access_controls(request, is_resource_level=True)

        return self._get_access_controls(request, is_resource_level=True)

    @extend_schema(exclude=True)
    @action(methods=["GET", "PUT"], detail=True)
    def global_access_controls(self, request: Request, *args, **kwargs):
        """
        DEPRECATED - use resource_access_controls instead.
        """
        if request.method == "PUT":
            return self._update_access_controls(request, is_resource_level=True)

        return self._get_access_controls(request, is_resource_level=True)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True)
    def users_with_access(self, request: Request, *args, **kwargs):
        """
        Get all users with access to this resource, including explicit and implicit access.
        """
        return self._get_users_with_access(request)

    # ----------------------------------------------------------------
    # Endpoints for the new access control settings UI
    # ----------------------------------------------------------------

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_defaults")
    def access_control_defaults(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        default_access_controls = AccessControl.objects.filter(team=team, organization_member=None, role=None)

        project_access_level: AccessControlLevel = default_access_level("project")
        saved_resource_levels: dict[str, str] = {}

        for ac in default_access_controls:
            if ac.resource == "project":
                project_access_level = ac.access_level
            elif ac.resource_id is None and ac.resource in set(ACCESS_CONTROL_RESOURCES):
                saved_resource_levels[ac.resource] = ac.access_level

        resource_access_levels = {
            r: {
                "access_level": saved_resource_levels.get(r),
                # What applies when no rule exists anywhere, so the UI can spell out the fallback
                "system_default_access_level": default_access_level(r),
                "minimum": minimum_access_level(r),
                "maximum": highest_access_level(r),
            }
            for r in ACCESS_CONTROL_RESOURCES
        }

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": user_access_control.check_can_modify_access_levels_for_object(team),
                "project_access_level": project_access_level,
                "resource_access_levels": resource_access_levels,
                "object_rule_resources": sorted(resources_with_object_access_controls()),
            }
        )

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_roles")
    def access_control_roles(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        access_controls = AccessControl.objects.filter(team=team).filter(Q(resource="project") | Q(resource_id=None))

        # Build lookup dicts from saved access controls
        project_default_level: AccessControlLevel = default_access_level("project")
        resource_default_levels: dict[APIScopeObject, AccessControlLevel] = {}
        role_project_overrides: dict[str, AccessControlLevel] = {}
        role_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}

        for ac in access_controls:
            level: AccessControlLevel = ac.access_level
            resource_type: APIScopeObject = ac.resource
            role_id = ac.role_id
            is_default = ac.organization_member_id is None and role_id is None

            if is_default:
                if ac.resource == "project":
                    project_default_level = level
                else:
                    resource_default_levels[resource_type] = level
            elif role_id:
                if ac.resource == "project":
                    role_project_overrides[str(role_id)] = level
                else:
                    role_resource_overrides[(str(role_id), resource_type)] = level

        # Role overrides (project- and resource-level) only take effect if the
        # organization has the ROLE_BASED_ACCESS feature; otherwise role rows in the
        # DB are inert and we must not surface them as the effective access level.
        role_based_access_supported = team.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

        # Build results for each role
        roles = Role.objects.filter(organization=team.organization)
        # An optional role_id narrows the walk to one role, so the detail panel doesn't pay for the whole list
        if request.query_params.get("role_id"):
            roles = roles.filter(id=self._get_role(request, team).id)
        results = []

        for role in roles:
            rid = str(role.id)

            project_role_level = role_project_overrides.get(rid) if role_based_access_supported else None
            project_result = get_effective_access_level_for_role(
                resource="project",
                default_level=project_default_level,
                role_level=project_role_level,
            )

            resource_entries: dict[str, dict] = {}
            for resource in ACCESS_CONTROL_RESOURCES:
                resource_role_level = (
                    role_resource_overrides.get((rid, resource)) if role_based_access_supported else None
                )
                resource_default = resource_default_levels.get(resource)
                resource_result = get_effective_access_level_for_role(
                    resource=resource,
                    default_level=resource_default,
                    role_level=resource_role_level,
                )
                resource_entries[resource] = {
                    "access_level": resource_role_level,
                    "effective_access_level": resource_result.effective_access_level,
                    "inherited_access_level": resource_result.inherited_access_level,
                    "inherited_access_level_reason": resource_result.inherited_access_level_reason,
                    "minimum": minimum_access_level(resource),
                    "maximum": highest_access_level(resource),
                }

            results.append(
                {
                    "role_id": role.id,
                    "role_name": role.name,
                    "project": {
                        "access_level": project_role_level,
                        "effective_access_level": project_result.effective_access_level,
                        "inherited_access_level": project_result.inherited_access_level,
                        "inherited_access_level_reason": project_result.inherited_access_level_reason,
                        "minimum": minimum_access_level("project"),
                        "maximum": highest_access_level("project"),
                    },
                    "resources": resource_entries,
                }
            )

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": user_access_control.check_can_modify_access_levels_for_object(team),
                "results": results,
            }
        )

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_members")
    def access_control_members(self, request: Request, *args, **kwargs):
        team = cast(Team, self.team)  # type: ignore
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore

        access_controls = AccessControl.objects.filter(team=team).filter(Q(resource="project") | Q(resource_id=None))

        # Build lookup dicts from saved access controls
        project_default_level: AccessControlLevel = default_access_level("project")
        resource_default_levels: dict[APIScopeObject, AccessControlLevel] = {}
        role_project_overrides: dict[str, AccessControlLevel] = {}
        role_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}
        member_project_overrides: dict[str, AccessControlLevel] = {}
        member_resource_overrides: dict[tuple[str, APIScopeObject], AccessControlLevel] = {}

        for ac in access_controls:
            level: AccessControlLevel = ac.access_level
            resource_type: APIScopeObject = ac.resource
            role_id = ac.role_id
            member_id = ac.organization_member_id
            is_default = member_id is None and role_id is None

            if is_default:
                if ac.resource == "project":
                    project_default_level = level
                else:
                    resource_default_levels[resource_type] = level
            elif role_id:
                if ac.resource == "project":
                    role_project_overrides[str(role_id)] = level
                else:
                    role_resource_overrides[(str(role_id), resource_type)] = level
            elif member_id:
                if ac.resource == "project":
                    member_project_overrides[str(member_id)] = level
                else:
                    member_resource_overrides[(str(member_id), resource_type)] = level

        # Role overrides (project- and resource-level) only take effect if the
        # organization has the ROLE_BASED_ACCESS feature; otherwise role rows in the
        # DB are inert and we must not let them influence members' effective access.
        role_based_access_supported = team.organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)

        # Build results for each member
        memberships = (
            OrganizationMembership.objects.filter(organization=team.organization, user__is_active=True)
            .select_related("user")
            .prefetch_related("role_memberships")
        )
        # An optional member_id narrows the walk to one member, so the detail panel doesn't pay for the whole list
        if request.query_params.get("member_id"):
            memberships = memberships.filter(id=self._get_membership(request, team).id)

        can_edit = user_access_control.check_can_modify_access_levels_for_object(team)
        hide_non_project_members = (
            not team.organization.members_can_see_org_members and not user_access_control.is_organization_admin
        )

        results = []
        for membership in memberships:
            mid = str(membership.id)
            is_org_admin = membership.level >= OrganizationMembership.Level.ADMIN
            # Role memberships only contribute when ROLE_BASED_ACCESS is enabled.
            member_role_ids = (
                [str(rm.role_id) for rm in membership.role_memberships.all()] if role_based_access_supported else []
            )

            project_member_level = member_project_overrides.get(mid)
            project_role_levels: list[AccessControlLevel] = [
                role_project_overrides[rid] for rid in member_role_ids if rid in role_project_overrides
            ]
            project_result = get_effective_access_level_for_member(
                resource="project",
                default_level=project_default_level,
                role_levels=project_role_levels,
                member_level=project_member_level,
                is_org_admin=is_org_admin,
            )

            # When the org restricts member list visibility, project members only see users with
            # project-scoped access (explicit grant, role, or default) — org admins aren't implied in
            if hide_non_project_members:
                project_scoped_result = get_effective_access_level_for_member(
                    resource="project",
                    default_level=project_default_level,
                    role_levels=project_role_levels,
                    member_level=project_member_level,
                    is_org_admin=False,
                )
                if project_scoped_result.effective_access_level in (None, "none"):
                    continue

            resource_entries: dict[str, dict] = {}
            for resource in ACCESS_CONTROL_RESOURCES:
                resource_member_level = member_resource_overrides.get((mid, resource))
                resource_default = resource_default_levels.get(resource)
                resource_role_levels: list[AccessControlLevel] = [
                    role_resource_overrides[(rid, resource)]
                    for rid in member_role_ids
                    if (rid, resource) in role_resource_overrides
                ]
                resource_result = get_effective_access_level_for_member(
                    resource=resource,
                    default_level=resource_default,
                    role_levels=resource_role_levels,
                    member_level=resource_member_level,
                    is_org_admin=is_org_admin,
                )
                resource_entries[resource] = {
                    "access_level": resource_member_level,
                    "effective_access_level": resource_result.effective_access_level,
                    "inherited_access_level": resource_result.inherited_access_level,
                    "inherited_access_level_reason": resource_result.inherited_access_level_reason,
                    "minimum": minimum_access_level(resource),
                    "maximum": highest_access_level(resource),
                }

            user = membership.user
            results.append(
                {
                    "organization_membership_id": membership.id,
                    "user": {
                        "uuid": user.uuid,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                    },
                    "organization_level": membership.level,
                    "project": {
                        "access_level": project_member_level,
                        "effective_access_level": project_result.effective_access_level,
                        "inherited_access_level": project_result.inherited_access_level,
                        "inherited_access_level_reason": project_result.inherited_access_level_reason,
                        "minimum": minimum_access_level("project"),
                        "maximum": highest_access_level("project"),
                    },
                    "resources": resource_entries,
                }
            )

        return Response(
            {
                "available_project_levels": list(ordered_access_levels("project")),
                "available_resource_levels": list(ACCESS_CONTROL_LEVELS_RESOURCE),
                "can_edit": can_edit,
                "results": results,
            }
        )

    def _get_membership(self, request: Request, team: Team) -> OrganizationMembership:
        member_id = request.query_params.get("member_id")
        if not member_id:
            raise exceptions.ValidationError("member_id is required")
        return get_object_or_404(OrganizationMembership, id=member_id, organization=team.organization)

    def _get_role(self, request: Request, team: Team) -> Role:
        role_id = request.query_params.get("role_id")
        if not role_id:
            raise exceptions.ValidationError("role_id is required")
        return get_object_or_404(Role, id=role_id, organization=team.organization)

    def _object_rules_response(
        self,
        team: Team,
        *,
        membership: OrganizationMembership | None = None,
        role: Role | None = None,
    ) -> Response:
        """Object-level rules belonging to one subject: a member, a role, or the project itself.

        Passing neither a member nor a role targets the project-wide rules, the ones that apply to
        everyone without a rule of their own.

        Deliberately returns only the subject's own rules, without resolving what would apply in
        their absence — object-level resolution differs between code paths today (explicit-wins vs
        max), so surfacing a computed fallback here would be wrong in edge cases. Revisit once
        resolution returns the level together with its source.
        """
        rule_filter: dict[str, Any]
        if membership is not None:
            rule_filter = {"organization_member": membership}
        elif role is not None:
            rule_filter = {"role": role}
        else:
            # Project-wide rules are the rows with no subject at all
            rule_filter = {"organization_member": None, "role": None}
        rows = list(
            AccessControl.objects.filter(team=team, resource_id__isnull=False, **rule_filter).exclude(
                resource="project"
            )
        )
        if not rows:
            return Response({"results": []})

        ids_by_resource: dict[str, list[str]] = defaultdict(list)
        for ac in rows:
            ids_by_resource[ac.resource].append(ac.resource_id)
        names_by_resource = {
            resource: _resolve_object_names(resource, ids, team.id) for resource, ids in ids_by_resource.items()
        }

        results = []
        for ac in rows:
            resolved = names_by_resource.get(ac.resource, {}).get(str(ac.resource_id))
            results.append(
                {
                    "resource": ac.resource,
                    "resource_id": ac.resource_id,
                    "name": (resolved.name if resolved else None) or ac.resource_id,
                    "short_id": resolved.short_id if resolved else None,
                    "access_level": ac.access_level,
                }
            )
        results.sort(key=lambda r: (r["resource"], (r["name"] or "").lower()))
        return Response({"results": results})

    def _property_rules_response(
        self,
        team: Team,
        *,
        organization_member: OrganizationMembership | None = None,
        role: Role | None = None,
    ) -> Response:
        """Property rules belonging to one subject, including read & write grants over a stricter default."""
        from products.access_control.backend.facade.api import (
            list_property_access_controls,  # noqa: PLC0415 — the facade imports ee models, a module-level import would be circular
        )

        rules = list_property_access_controls(
            team_id=team.id,
            organization_member_id=organization_member.id if organization_member else None,
            role_id=role.id if role else None,
        )
        definitions_by_id = {
            str(pd.id): pd
            for pd in PropertyDefinition.objects.filter(id__in=[rule.property_definition_id for rule in rules])
        }

        results = []
        for rule in rules:
            pd = definitions_by_id.get(str(rule.property_definition_id))
            if pd is None:
                continue
            results.append(
                {
                    "property_definition_id": str(pd.id),
                    "property": pd.name,
                    "property_type": "person" if pd.type == pd.Type.PERSON else "event",
                    "access_level": rule.access_level.value,
                }
            )
        results.sort(key=lambda r: (r["property_type"], (r["property"] or "").lower()))
        return Response({"results": results})

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_default_objects")
    def access_control_default_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules that apply to everyone without a rule of their own."""
        team = cast(Team, self.team)  # type: ignore
        return self._object_rules_response(team)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_default_properties")
    def access_control_default_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions that apply to everyone without a rule of their own."""
        team = cast(Team, self.team)  # type: ignore
        return self._property_rules_response(team)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_member_objects")
    def access_control_member_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules configured for a member."""
        team = cast(Team, self.team)  # type: ignore
        membership = self._get_membership(request, team)
        return self._object_rules_response(team, membership=membership)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_member_properties")
    def access_control_member_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions configured for a member."""
        team = cast(Team, self.team)  # type: ignore
        membership = self._get_membership(request, team)
        return self._property_rules_response(team, organization_member=membership)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_role_objects")
    def access_control_role_objects(self, request: Request, *args, **kwargs) -> Response:
        """Object-level access rules configured for a role."""
        team = cast(Team, self.team)  # type: ignore
        role = self._get_role(request, team)
        return self._object_rules_response(team, role=role)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True, url_path="access_control_role_properties")
    def access_control_role_properties(self, request: Request, *args, **kwargs) -> Response:
        """Property restrictions configured for a role."""
        team = cast(Team, self.team)  # type: ignore
        role = self._get_role(request, team)
        return self._property_rules_response(team, role=role)
