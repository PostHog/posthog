from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Optional, cast

from django.db.models import Model

from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, APIScopeObjectOrNotSupported

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    ACCESS_CONTROL_MAX_OBJECTS_PER_RESOURCE,
    AccessSource,
    ResolvedAccess,
    UserAccessControl,
    default_access_level,
    fallback_parent_object,
    get_field_access_control_map,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
    resource_to_display_name,
)
from products.access_control.backend.models.access_control import AccessControl

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


def _inherited_source_display_name(obj: Model, access: ResolvedAccess) -> str | None:
    """A human name for the parent object an inherited level comes through, so the UI can say
    which one. Only object-scoped sources have one, and the parent is always the object's own
    fallback relation (that's where the walk got its id), so it is read off the object — cached
    by Django, free when already loaded — never refetched by id. The name field comes from the
    same registry the settings UI names objects with, so a new fallback parent needs no code here."""
    from .access_control_settings import (
        _display_model,  # noqa: PLC0415 — access_control_settings imports this module; deferring breaks the cycle
    )

    if access.source != "parent_object":
        return None
    parent = fallback_parent_object(obj, access.source_resource)
    display = _display_model(access.source_resource)
    if parent is None or display is None:
        return None
    name = getattr(parent, display.name_field, None)
    return str(name) if name else None


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


class ResolvedAccessSerializer(serializers.Serializer):
    """A resolved access level with the rule that supplied it — the wire form of `ResolvedAccess`."""

    access_level = serializers.CharField(help_text="The access level that applies.")
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=[
            "object",
            "parent_object",
            "resource",
            "parent_resource",
            "system_default",
            "org_admin",
            "creator",
            "org_membership",
        ],
        help_text="How the level was derived: a rule on the object, its parent object, the resource, the parent "
        "resource, the built-in default, or one of the bypasses (org admin, creator, organization membership).",
    )
    source_subject = serializers.ChoiceField(
        choices=["member", "role", "default"],
        allow_null=True,
        help_text="Whose rule decided: a member's own, a role's, or the default for everyone. Null when no rule did.",
    )
    source_resource = serializers.CharField(help_text="The resource the deciding rule belongs to.")
    source_resource_id = serializers.CharField(
        allow_null=True,
        help_text="The deciding rule's object id, when it is an object-level rule (e.g. the source a table inherits from).",
    )


class InheritedAccessSerializer(ResolvedAccessSerializer):
    """The level an object falls back to without its own override, plus a display name for the parent it
    comes through when there is one."""

    source_display_name = serializers.CharField(
        allow_null=True,
        help_text="A human name for the parent object the level comes through (e.g. a table's source type).",
    )


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

        # Neither relation is scoped by organization on the way in, so a rule could otherwise name
        # a role or member from a different organization and cross the authorization boundary
        if data.get("role") and data["role"].organization_id != team.organization_id:
            raise serializers.ValidationError("The role must belong to the same organization as this project.")

        if data.get("organization_member") and data["organization_member"].organization_id != team.organization_id:
            raise serializers.ValidationError("The member must belong to the same organization as this project.")

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


def upsert_access_control(
    *,
    team: Team,
    user_access_control: UserAccessControl,
    build_serializer: Callable[[AccessControl | None], AccessControlSerializer],
) -> Response:
    """Apply one validated access control rule: a null level deletes the subject's rule, any other
    level creates or updates it. Shared by the per-resource PUT actions and the settings page's
    generic object-rule write, so validation and cache behavior cannot drift between them."""
    serializer = build_serializer(None)
    serializer.is_valid(raise_exception=True)
    params = serializer.validated_data

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
            user_access_control._clear_cache()
        return Response(status=status.HTTP_204_NO_CONTENT)

    if instance:
        serializer = build_serializer(instance)
        serializer.is_valid(raise_exception=True)
    serializer.validated_data["team"] = team
    serializer.save()
    # Drop the preloaded access-control snapshot so later reads this request are fresh.
    user_access_control._clear_cache()

    return Response(serializer.data, status=status.HTTP_200_OK)


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
            # can spell out what removing the override means. Resolved by the access walker itself
            # (the object's own rows masked out, everyone perspective), so the shown level cannot
            # disagree with how access is actually enforced — a re-derivation here would miss the
            # fallback-parent tier (a table gated by its source).
            #
            # None for a project is load-bearing: it is what stops the UI offering "No override" on
            # a project's own default, which has nothing above it to fall back to. "No override"
            # belongs to object defaults only — project-level access is configured in its own
            # panel, which has no inherited tier to fall back to.
            inherited = SubjectAccessControl.for_default(user_access_control, team).inherited_access_for_object(obj)
            payload["inherited_access"] = (
                InheritedAccessSerializer(
                    {**asdict(inherited), "source_display_name": _inherited_source_display_name(obj, inherited)}
                ).data
                if inherited
                else None
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
        # nosemgrep: api-response-must-match-schema -- unchanged response shape moved into the product boundary
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

        return upsert_access_control(
            team=team,
            user_access_control=self.user_access_control,  # type: ignore[attr-defined]
            build_serializer=lambda instance: self._get_access_control_serializer(instance, data=request.data),
        )

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
        request = self.context.get("request")

        # The user could be anonymous - if so there is no access control to be used
        if request and request.user.is_anonymous:
            return None

        # NOTE: The user_access_control is typically on the view but in specific cases,
        # such as rendering HTML (`render_template()`), it is set at the context level
        if "user_access_control" in self.context:
            # Get it directly from the context
            return self.context["user_access_control"]
        elif hasattr(self.context.get("view", None), "user_access_control"):
            # Otherwise from the view (the default case)
            return self.context["view"].user_access_control
        elif request:
            user = cast(User, request.user)
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

            # Check if user has the required access level.
            # "project" access is object-level (checked against the Team instance), not resource-level.
            # For models with a team FK (e.g. Team extensions), use the team for the project check.
            if resource == "project":
                obj_for_check = getattr(self.instance, "team", self.instance)
                has_access = user_access_control.check_access_level_for_object(obj_for_check, required_level)
            else:
                has_access = user_access_control.check_access_level_for_resource(resource, required_level)

            if not has_access:
                display_name = resource_to_display_name(resource)
                raise serializers.ValidationError(
                    {field_name: f"You need {required_level} access to {display_name} to modify this field."}
                )

        return attrs
