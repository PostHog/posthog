from rest_framework import mixins, serializers, viewsets

from ee.api.role import RolePermissions
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.api.routing import StructuredViewSetMixin


class OrganizationResourceAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationResourceAccess
        fields = [
            "id",
            "resource",
            "access_level",
            "organization",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by", "organization"]

    def validate_resource(self, resource):
        if OrganizationResourceAccess.objects.filter(
            organization=self.context["request"].user.organization,
            resource=resource,
        ).exists():
            raise serializers.ValidationError("This resource access already exists.", code="unique")
        return resource

    def create(self, validated_data):
        validated_data["organization"] = self.context["request"].user.organization
        return super().create(validated_data)


class OrganizationResourceAccessViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    additional_permission_classes = [RolePermissions]
    serializer_class = OrganizationResourceAccessSerializer
    queryset = OrganizationResourceAccess.objects.all()
