from collections import OrderedDict
from typing import cast

from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response

from ee.models.rbac.access_control import AccessControl
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import API_SCOPE_OBJECTS
from posthog.permissions import PremiumFeaturePermission
from posthog.rbac.user_access_control import UserAccessControl, ordered_access_levels


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
        # Ensure that only one of organization_member or role is set
        if data.get("organization_member") and data.get("role"):
            raise serializers.ValidationError("You can not scope an access control to both a member and a role.")

        access_control = cast(UserAccessControl, self.context["view"].user_access_control)
        resource = data["resource"]
        resource_id = data.get("resource_id")

        # We assume the highest level is required for the given resource to edit access controls
        required_level = ordered_access_levels(resource)[-1]

        # NOTE: For specific resources you are permitted if you are:
        # 1. The creator of the resource
        # 2. An Organization admin
        # 3. A Project admin

        if resource_id:
            # Check that they have the right access level for this specific resource object
            if not access_control.check_access_level_for_object(
                resource, data["resource_id"], required_level=required_level
            ):
                # TODO: Human readable resource name
                raise exceptions.PermissionDenied(f"Must be {required_level} to modify {resource} permissions.")
        else:
            # If modifying the base resource rules then we are checking the parent membership (project or organization)
            # NOTE: Currently we only support org level in the UI so its simply an org level check
            if not access_control.check_access_level_for_object("organization", required_level="admin"):
                raise exceptions.PermissionDenied("Must be an Organization admin to modify project-wide permissions.")

        return data


class AccessControlLimitOffsetPagination(LimitOffsetPagination):
    """
    To help the UI do its job we can return information about the access levels for the requested resource
    """

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.count),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("available_access_levels", ordered_access_levels(self.request.GET.get("resource"))),
                    ("results", data),
                ]
            )
        )

    def get_paginated_response_schema(self, schema):
        schema = super().get_paginated_response_schema(schema)

        schema["properties"]["available_access_levels"] = {
            "type": "array",
            "items": {"type": "string"},
        }

        return schema


class AccessControlViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    serializer_class = AccessControlSerializer
    queryset = AccessControl.objects.all()
    permission_classes = [PremiumFeaturePermission]
    # NOTE: DashboardCollaborators that should be replaced by this use ADVANCED_PERMISSIONS - what do with that?
    premium_feature = AvailableFeature.PROJECT_BASED_PERMISSIONING
    pagination_class = AccessControlLimitOffsetPagination

    def filter_queryset(self, queryset):
        params = self.request.GET

        if params.get("resource"):
            queryset = queryset.filter(resource=params["resource"])

        if params.get("resource_id"):
            queryset = queryset.filter(resource_id=params["resource_id"])
        elif params.get("resource"):
            queryset = queryset.filter(resource_id=None)

        return queryset

    def put(self, request: Request, *args, **kwargs):
        # Generically validate the incoming data
        partial_serializer = self.get_serializer(data=request.data)
        partial_serializer.is_valid(raise_exception=True)
        params = partial_serializer.validated_data

        instance = self.queryset.filter(
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
            serializer = self.get_serializer(instance, data=request.data)
        else:
            serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        serializer.validated_data["team"] = self.team
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(methods=["GET"], detail=False)
    def check(self, request: Request, *args, **kwargs):
        resource = request.GET.get("resource")
        resource_id = request.GET.get("resource_id")

        if not resource:
            raise exceptions.ValidationError("Resource must be provided.")

        control = self.user_access_control.access_control_for_object(resource, resource_id)
        return Response(
            {
                "access_level": control.access_level if control else None,
                "available_access_levels": ordered_access_levels(resource),
            },
            status=status.HTTP_403_FORBIDDEN,
        )


class AccessControlViewSetMixin:
    """
    Adds an "access_control" action to the viewset that handles access control for the given resource
    """

    @action(methods=["GET", "PATCH"], detail=True, url_path="access_control")
    def access_control(self, request: Request, *args, **kwargs):
        resource = request.GET.get("resource")
        resource_id = request.GET.get("resource_id")

        if not resource:
            raise exceptions.ValidationError("Resource must be provided.")

        control = self.user_access_control.access_control_for_object(resource, resource_id)
        return Response(
            {
                "access_level": control.access_level if control else None,
                "available_access_levels": ordered_access_levels(resource),
            },
            status=status.HTTP_403_FORBIDDEN,
        )
