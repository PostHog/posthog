from typing import TYPE_CHECKING, cast

from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.documentation import extend_schema
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    ACCESS_CONTROL_RESOURCES,
    AccessControlLevel,
    AccessSource,
    UserAccessControl,
    compute_effective_access_level,
    default_access_level,
    highest_access_level,
    minimum_access_level,
    ordered_access_levels,
)
from posthog.scopes import API_SCOPE_OBJECTS, APIScopeObjectOrNotSupported

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
        if resource not in API_SCOPE_OBJECTS:
            raise serializers.ValidationError("Invalid resource. Must be one of: {}".format(API_SCOPE_OBJECTS))

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

        if resource_id:
            # Check that they have the right access level for this specific resource object
            if not access_control.check_can_modify_access_levels_for_object(the_object):
                raise exceptions.PermissionDenied(f"Must be {required_level} to modify {resource} permissions.")
        else:
            # If modifying the base resource rules then we are checking the parent membership (project or organization)
            # NOTE: Currently we only support org level in the UI so its simply an org level check
            if not access_control.check_can_modify_access_levels_for_object(team):
                raise exceptions.PermissionDenied("Must be an Organization admin to modify project-wide permissions.")

        return data


class AccessControlWithEffectiveSerializer(AccessControlSerializer):
    """Extended serializer that includes effective access level fields.
    Only used for project-level and resource-type-level settings endpoints.
    """

    effective_access_level = serializers.CharField(read_only=True, allow_null=True, required=False)
    effective_access_level_reason = serializers.CharField(read_only=True, allow_null=True, required=False)

    class Meta(AccessControlSerializer.Meta):
        fields = [
            *AccessControlSerializer.Meta.fields,
            "effective_access_level",
            "effective_access_level_reason",
        ]


def _annotate_effective_access_levels(
    access_controls: list[AccessControl],
    all_members: list[OrganizationMembership] | None = None,
    all_roles: list[Role] | None = None,
) -> list[AccessControl]:
    """
    Annotates each AccessControl instance with effective_access_level and
    effective_access_level_reason as transient attributes (not persisted).

    When all_members/all_roles are provided, synthesizes rows for member×resource
    and role×resource combinations that don't have explicit overrides, so the
    response contains effective levels for every member and role.

    Returns the (possibly extended) list of access controls.
    """
    defaults: dict[str, AccessControlLevel] = {}
    role_acs: list[AccessControl] = []
    member_acs: list[AccessControl] = []
    default_acs: list[AccessControl] = []

    for ac in access_controls:
        if ac.organization_member_id is None and ac.role_id is None:  # type: ignore[attr-defined]
            defaults[ac.resource] = cast(AccessControlLevel, ac.access_level)
            default_acs.append(ac)
        elif ac.role_id is not None:  # type: ignore[attr-defined]
            role_acs.append(ac)
        else:
            member_acs.append(ac)

    # {(role_id, resource): level} for looking up role overrides per member
    role_levels_lookup: dict[tuple[str, str], AccessControlLevel] = {
        (str(ac.role_id), ac.resource): cast(AccessControlLevel, ac.access_level)  # type: ignore[attr-defined]
        for ac in role_acs
    }

    # Determine which resources we're working with
    resources = list(defaults.keys())
    if all_members is not None or all_roles is not None:
        for r in ACCESS_CONTROL_RESOURCES:
            if r not in resources:
                resources.append(r)

    # Synthesize missing role×resource rows (access_level=None means no override exists)
    synthesized_role_acs: list[AccessControl] = []
    if all_roles is not None:
        existing_role_keys = {(str(ac.role_id), ac.resource) for ac in role_acs}  # type: ignore[attr-defined]
        for role in all_roles:
            for resource in resources:
                if (str(role.id), resource) not in existing_role_keys:
                    synthetic = AccessControl(
                        resource=resource,
                        access_level=None,
                        role_id=role.id,
                        organization_member=None,
                    )
                    synthesized_role_acs.append(synthetic)

    # Synthesize missing member×resource rows (access_level=None means no override exists)
    synthesized_member_acs: list[AccessControl] = []
    if all_members is not None:
        existing_member_keys = {
            (str(ac.organization_member_id), ac.resource)
            for ac in member_acs  # type: ignore[attr-defined]
        }
        for membership in all_members:
            for resource in resources:
                if (str(membership.id), resource) not in existing_member_keys:
                    synthetic = AccessControl(
                        resource=resource,
                        access_level=None,
                        organization_member=membership,
                        role=None,
                    )
                    synthesized_member_acs.append(synthetic)

    # Annotate default rows
    for ac in default_acs:
        ac.effective_access_level = ac.access_level  # type: ignore[attr-defined]
        ac.effective_access_level_reason = "project_default"  # type: ignore[attr-defined]

    # Annotate role rows (both real and synthesized)
    for ac in role_acs + synthesized_role_acs:
        resource_default = defaults.get(ac.resource, default_access_level(ac.resource))
        saved = cast(AccessControlLevel, ac.access_level) if ac.access_level is not None else "none"
        effective, reason = compute_effective_access_level(
            resource=ac.resource,
            saved_level=saved,
            saved_reason="role_override",
            default_level=resource_default,
            role_levels=[],
            is_org_admin=False,
        )
        ac.effective_access_level = effective  # type: ignore[attr-defined]
        ac.effective_access_level_reason = reason  # type: ignore[attr-defined]

    # Annotate member rows (both real and synthesized)
    for ac in member_acs + synthesized_member_acs:
        membership = ac.organization_member
        resource_default = defaults.get(ac.resource, default_access_level(ac.resource))

        is_org_admin = membership is not None and membership.level >= OrganizationMembership.Level.ADMIN

        member_role_levels: list[AccessControlLevel] = []
        if membership is not None and not is_org_admin:
            try:
                for rm in membership.role_memberships.all():
                    role_level = role_levels_lookup.get((str(rm.role_id), ac.resource))
                    if role_level:
                        member_role_levels.append(role_level)
            except Exception:
                pass

        saved = cast(AccessControlLevel, ac.access_level) if ac.access_level is not None else "none"
        effective, reason = compute_effective_access_level(
            resource=ac.resource,
            saved_level=saved,
            saved_reason="member_override",
            default_level=resource_default,
            role_levels=member_role_levels,
            is_org_admin=is_org_admin,
        )
        ac.effective_access_level = effective  # type: ignore[attr-defined]
        ac.effective_access_level_reason = reason  # type: ignore[attr-defined]

    return default_acs + role_acs + synthesized_role_acs + member_acs + synthesized_member_acs


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

        is_settings_endpoint = is_resource_level or resource == "project"

        if is_settings_endpoint:
            base_qs = AccessControl.objects.select_related("organization_member").prefetch_related(
                "organization_member__role_memberships"
            )
        else:
            base_qs = AccessControl.objects.all()

        if is_resource_level:
            # resource_id=None: type-level rules (e.g. "dashboards → editor for everyone"), not tied to a specific object
            access_controls = list(base_qs.filter(team=team, resource_id=None).all())
        else:
            # resource_id set: object-level rules for this specific resource instance (e.g. project, notebook #123)
            access_controls = list(base_qs.filter(team=team, resource=resource, resource_id=resource_id).all())

        if is_settings_endpoint:
            all_members = list(
                OrganizationMembership.objects.filter(
                    organization=team.organization, user__is_active=True
                ).prefetch_related("role_memberships")
            )
            all_roles = list(Role.objects.filter(organization=team.organization))

            access_controls = _annotate_effective_access_levels(
                access_controls, all_members=all_members, all_roles=all_roles
            )
            serializer_context = self.get_serializer_context()
            serializer = AccessControlWithEffectiveSerializer(
                instance=access_controls, many=True, context=serializer_context
            )
        else:
            serializer = self._get_access_control_serializer(instance=access_controls, many=True)

        user_access_level = user_access_control.get_user_access_level(obj)

        return Response(
            {
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
        )

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
        resource = getattr(self, "scope_object", None)
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
            return Response(status=status.HTTP_204_NO_CONTENT)

        # Perform the upsert
        if instance:
            serializer = self._get_access_control_serializer(instance, data=request.data)
        else:
            serializer = self._get_access_control_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        serializer.validated_data["team"] = team
        serializer.save()

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
