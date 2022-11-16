from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from ee.api.role import RolePermissions
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.api.routing import StructuredViewSetMixin
from posthog.permissions import OrganizationMemberPermissions


class OrganizationResourceAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationResourceAccess
        fields = ["id", "resource", "access_level", "created_at", "updated_at", "created_by"]
        read_only_fields = ["id", "created_at", "created_by"]

    # def validate_resource(self, resource):
    #     if OrganizationResourceAccess.objects.filter(resource=resource).exists():
    #         raise serializers.ValidationError("This resource access already exists.", code="unique")


class OrganizationResourceAccessViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        OrganizationMemberPermissions,
        RolePermissions,
    ]
    serializer_class = OrganizationResourceAccessSerializer
    queryset = OrganizationResourceAccess.objects.all()
