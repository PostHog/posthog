from typing import TYPE_CHECKING, cast


from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from posthog.api.documentation import extend_schema

from ee.models.rbac.access_control import AccessControl
from posthog.models.scopes import API_SCOPE_OBJECTS, APIScopeObjectOrNotSupported
from posthog.models.team.team import Team
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    UserAccessControl,
    default_access_level,
    highest_access_level,
    ordered_access_levels,
)


if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


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

    # Validate that resource is a valid option from the API_SCOPE_OBJECTS
    def validate_resource(self, resource):
        if resource not in API_SCOPE_OBJECTS:
            raise serializers.ValidationError("Invalid resource. Must be one of: {}".format(API_SCOPE_OBJECTS))

        return resource

    # Validate that access control is a valid option
    def validate_access_level(self, access_level):
        if access_level and access_level not in ordered_access_levels(self.initial_data["resource"]):
            raise serializers.ValidationError(
                f"Invalid access level. Must be one of: {', '.join(ordered_access_levels(self.initial_data['resource']))}"
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

    def _get_access_control_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())
        return AccessControlSerializer(*args, **kwargs)

    def _get_access_controls(self, request: Request, is_global=False):
        resource = cast(APIScopeObjectOrNotSupported, getattr(self, "scope_object", None))
        user_access_control = cast(UserAccessControl, self.user_access_control)  # type: ignore
        team = cast(Team, self.team)  # type: ignore

        if is_global and resource != "project" or not resource or resource == "INTERNAL":
            raise exceptions.NotFound("Role based access controls are only available for projects.")

        obj = self.get_object()
        resource_id = obj.id

        if is_global:
            # If role based then we are getting all controls for the project that aren't specific to a resource
            access_controls = AccessControl.objects.filter(team=team, resource_id=None).all()
        else:
            # Otherwise we are getting all controls for the specific resource
            access_controls = AccessControl.objects.filter(team=team, resource=resource, resource_id=resource_id).all()

        serializer = self._get_access_control_serializer(instance=access_controls, many=True)
        user_access_level = user_access_control.access_level_for_object(obj, resource)

        return Response(
            {
                "access_controls": serializer.data,
                # NOTE: For Role based controls we are always configuring resource level items
                "available_access_levels": ACCESS_CONTROL_LEVELS_RESOURCE
                if is_global
                else ordered_access_levels(resource),
                "default_access_level": "editor" if is_global else default_access_level(resource),
                "user_access_level": user_access_level,
                "user_can_edit_access_levels": user_access_control.check_can_modify_access_levels_for_object(obj),
            }
        )

    def _update_access_controls(self, request: Request, is_global=False):
        resource = getattr(self, "scope_object", None)
        obj = self.get_object()
        resource_id = str(obj.id)
        team = cast(Team, self.team)  # type: ignore

        # Generically validate the incoming data
        if not is_global:
            # If not role based we are deriving from the viewset
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
        if request.method == "PUT":
            return self._update_access_controls(request)

        return self._get_access_controls(request)

    @extend_schema(exclude=True)
    @action(methods=["GET", "PUT"], detail=True)
    def global_access_controls(self, request: Request, *args, **kwargs):
        if request.method == "PUT":
            return self._update_access_controls(request, is_global=True)

        return self._get_access_controls(request, is_global=True)
