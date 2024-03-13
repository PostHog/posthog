from rest_framework import serializers, mixins, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.api.rbac.role import RoleSerializer
from ee.models.rbac.access_control import AccessControl
from posthog.api.organization_member import OrganizationMemberSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.team import TeamSerializer
from posthog.models.personal_api_key import API_SCOPE_OBJECTS


# TODO: Validate that an access control can only have one of team, organization_membership, or role


class AccessControlSerializer(serializers.ModelSerializer):
    access_level = serializers.CharField(allow_null=True)
    organization_membership = OrganizationMemberSerializer(required=False)
    role = RoleSerializer(required=False)
    # team = TeamSerializer() # TOOD: This crashes for some reason

    class Meta:
        model = AccessControl
        fields = [
            "resource",
            "resource_id",
            "access_level",
            "team",
            "organization_membership",
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
        # Ensure that only one of team, organization_membership, or role is set
        if sum([bool(data.get("team")), bool(data.get("organization_membership")), bool(data.get("role"))]) != 1:
            raise serializers.ValidationError(
                "Exactly one of 'team', 'organization_membership', or 'role' must be set."
            )

        return data


class AccessControlViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    # TODO: Add permissions
    serializer_class = AccessControlSerializer
    queryset = AccessControl.objects.all()

    def put(self, request: Request, *args, **kwargs):
        # Generically validate the incoming data
        partial_serializer = self.get_serializer(data=request.data)
        partial_serializer.is_valid(raise_exception=True)
        params = partial_serializer.validated_data

        instance = self.queryset.filter(
            resource=params["resource"],
            resource_id=params.get("resource_id"),
            organization_membership=params.get("organization_membership"),
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
