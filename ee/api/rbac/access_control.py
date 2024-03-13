from rest_framework import serializers, viewsets

from ee.models.rbac.access_control import AccessControl
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.personal_api_key import API_SCOPE_OBJECTS


# TODO: Validate that an access control can only have one of team, organization_membership, or role


class AccessControlSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessControl
        fields = [
            "id",
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

    def create(self, validated_data):
        validated_data["organization"] = self.context["organization"]
        return super().create(validated_data)


class AccessControlViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    # TODO: Add permissions
    serializer_class = AccessControlSerializer
    queryset = AccessControl.objects.all()
