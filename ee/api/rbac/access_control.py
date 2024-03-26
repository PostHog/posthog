from typing import cast


from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.models.rbac.access_control import AccessControl
from posthog.models.scopes import API_SCOPE_OBJECTS
from posthog.rbac.user_access_control import (
    ACCESS_CONTROL_LEVELS_RESOURCE,
    UserAccessControl,
    default_access_level,
    highest_access_level,
    ordered_access_levels,
)


class AccessControlSerializer(serializers.ModelSerializer):
    access_level = serializers.CharField(allow_null=True)

    class Meta:
        model = AccessControl
        fields = [
            "resource",
            "resource_id",
            "access_level",
            "organization_member",
            "role",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate_resource(self, resource):
        if resource not in API_SCOPE_OBJECTS:
            raise serializers.ValidationError("Invalid resource. Must be one of: {}".format(API_SCOPE_OBJECTS))

        return resource

    # validate that access control is a valid option
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


class AccessControlViewSetMixin:
    """
    Adds an "access_controls" action to the viewset that handles access control for the given resource

    Why a mixin? We want to easily add this to any existing resource, including providing easy helpers for adding access control info such
    as the current users access level to any response.
    """

    # 1. Know that the project level access is covered by the Permission check
    # 2. Get the actual object which we can pass to the serializer to check if the user created it
    # 3. We can also use the serializer to check the access level for the object

    # TODO: Probably move this to the TeamAndOrgViewSetMixin
    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        # TODO: Detect GET param to include hidden resources (for admins)

        if self.action != "list":
            # NOTE: If we are getting an individual object then we don't filter it out here - this is handled by the permission logic
            # The reason being, that if we filter out here already, we can't load the object which is required for checking access controls for it
            return queryset
        queryset = self.user_access_control.filter_queryset_by_access_level(queryset)

        return queryset

    def _get_access_control_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", self.get_serializer_context())
        return AccessControlSerializer(*args, **kwargs)

    def _get_access_controls(self, request: Request, role_based=False):
        resource = getattr(self, "scope_object", None)

        if role_based and resource != "project":
            raise exceptions.NotFound("Role based access controls are only available for projects.")

        obj = self.get_object()
        resource_id = obj.id

        if role_based:
            # If role based then we are getting all controls for the project that aren't specific to a resource
            access_controls = AccessControl.objects.filter(team=self.team, resource_id=None).all()
        else:
            # Otherwise we are getting all controls for the specific resource
            access_controls = AccessControl.objects.filter(
                team=self.team, resource=resource, resource_id=resource_id
            ).all()

        serializer = self._get_access_control_serializer(instance=access_controls, many=True)
        user_access_level = self.user_access_control.access_level_for_object(obj, resource)

        return Response(
            {
                "access_controls": serializer.data,
                # NOTE: For Role based controls we are always configuring resource level items
                "available_access_levels": ACCESS_CONTROL_LEVELS_RESOURCE
                if role_based
                else ordered_access_levels(resource),
                "default_access_level": "editor" if role_based else default_access_level(resource),
                "user_access_level": user_access_level,
                "user_can_edit_access_levels": self.user_access_control.check_can_modify_access_levels_for_object(obj),
            }
        )

    def _update_access_controls(self, request: Request, role_based=False):
        resource = getattr(self, "scope_object", None)
        obj = self.get_object()
        resource_id = str(obj.id)

        # Generically validate the incoming data
        if not role_based:
            # If not role based we are deriving from the viewset
            data = request.data
            data["resource"] = resource
            data["resource_id"] = resource_id

        partial_serializer = self._get_access_control_serializer(data=request.data)
        partial_serializer.is_valid(raise_exception=True)
        params = partial_serializer.validated_data

        instance = AccessControl.objects.filter(
            team=self.team,
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
        serializer.validated_data["team"] = self.team
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(methods=["GET", "PUT"], detail=True)
    def access_controls(self, request: Request, *args, **kwargs):
        if request.method == "GET":
            return self._get_access_controls(request)
        if request.method == "PUT":
            return self._update_access_controls(request)

    @action(methods=["GET", "PUT"], detail=True)
    def role_based_access_controls(self, request: Request, *args, **kwargs):
        if request.method == "GET":
            return self._get_access_controls(request, role_based=True)
        if request.method == "PUT":
            return self._update_access_controls(request, role_based=True)
