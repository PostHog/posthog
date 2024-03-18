from typing import cast

from rest_framework import exceptions, mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.models.rbac.access_control import AccessControl
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import API_SCOPE_OBJECTS
from posthog.permissions import PremiumFeaturePermission
from posthog.rbac.user_access_control import UserAccessControl

# TODO: Validate that an access control can only have one of team, organization_member, or role


class AccessControlSerializer(serializers.ModelSerializer):
    access_level = serializers.CharField(allow_null=True)

    class Meta:
        model = AccessControl
        fields = [
            "resource",
            "resource_id",
            "access_level",
            "team",
            "organization_member",
            "role",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "organization"]

    def validate_resource(self, resource):
        if resource not in API_SCOPE_OBJECTS:
            raise serializers.ValidationError("Invalid resource. Must be one of: {}".format(API_SCOPE_OBJECTS))

        return resource

    def validate(self, data):
        # Ensure that only one of team, organization_member, or role is set
        if sum([bool(data.get("team")), bool(data.get("organization_member")), bool(data.get("role"))]) != 1:
            raise serializers.ValidationError("Exactly one of 'team', 'organization_member', or 'role' must be set.")

        access_control = cast(UserAccessControl, self.context["view"].user_access_control)
        resource = data["resource"]
        resource_id = data.get("resource_id")

        if resource == "project" and resource_id:
            # Special check for modifying a specific project's access
            if not access_control.check_access_level_for_object("project", data["resource_id"], "admin"):
                raise exceptions.PermissionDenied("You do not have the required access to this project.")

        # team: Team = self.context["get_team"]()
        # if not team.access_control:
        #     raise exceptions.ValidationError(
        #         "Explicit members can only be accessed for projects with project-based permissioning enabled."
        #     )
        # requesting_user: User = self.context["request"].user
        # membership_being_accessed = cast(Optional[ExplicitTeamMembership], self.instance)
        # try:
        #     requesting_level = self.user_permissions.team(team).effective_membership_level
        # except OrganizationMembership.DoesNotExist:
        #     # Requesting user does not belong to the project's organization, so we spoof a 404 for enhanced security
        #     raise exceptions.NotFound("Project not found.")

        # new_level = attrs.get("level")

        # if requesting_level is None:
        #     raise exceptions.PermissionDenied("You do not have the required access to this project.")

        # if attrs.get("user_uuid") == requesting_user.uuid:
        #     # Create-only check
        #     raise exceptions.PermissionDenied("You can't explicitly add yourself to projects.")

        # if new_level is not None and new_level > requesting_level:
        #     raise exceptions.PermissionDenied("You can only set access level to lower or equal to your current one.")

        # if membership_being_accessed is not None:
        #     # Update-only checks
        #     if membership_being_accessed.parent_membership.user_id != requesting_user.id:
        #         # Requesting user updating someone else
        #         if membership_being_accessed.level > requesting_level:
        #             raise exceptions.PermissionDenied("You can only edit others with level lower or equal to you.")
        #     else:
        #         # Requesting user updating themselves
        #         if new_level is not None:
        #             raise exceptions.PermissionDenied("You can't set your own access level.")

        return data


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
            resource=params["resource"],
            resource_id=params.get("resource_id"),
            organization_member=params.get("organization_member"),
            team=params.get("team"),
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
        serializer.validated_data["organization"] = self.organization
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)
