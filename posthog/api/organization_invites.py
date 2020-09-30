from typing import Any, Dict

from django.db.models import QuerySet, query
from rest_framework import exceptions, mixins, response, serializers, status, viewsets

from posthog.models import OrganizationInvite
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions


class OrganizationInviteSerializer(serializers.ModelSerializer):
    last_used_by_id = serializers.IntegerField(source="last_used_by.id", read_only=True)
    last_used_by_email = serializers.CharField(source="last_used_by.email", read_only=True)
    last_used_by_first_name = serializers.CharField(source="last_used_by.first_name", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    created_by_first_name = serializers.CharField(source="created_by.first_name", read_only=True)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
            "uses",
            "max_uses",
            "last_used_by_id",
            "last_used_by_email",
            "last_used_by_first_name",
            "created_by_id",
            "created_by_email",
            "created_by_first_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "uses",
            "last_used_by_id",
            "last_used_by_email",
            "last_used_by_first_name",
            "created_by_id",
            "created_by_email",
            "created_by_first_name",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> OrganizationInvite:
        request = self.context["request"]
        invite = OrganizationInvite.objects.create(
            organization=request.user.organization, created_by=request.user, **validated_data
        )
        return invite


class OrganizationInviteViewSet(
    mixins.DestroyModelMixin, mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    serializer_class = OrganizationInviteSerializer
    pagination_class = None
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationInvite.objects.none()
    lookup_field = "id"

    def get_queryset(self) -> QuerySet:
        return (
            OrganizationInvite.objects.filter(organization=self.request.user.organization)
            .select_related("created_by")
            .select_related("last_used_by")
            .order_by("-created_at")
        )

    def destroy(self, request, *args, **kwargs):
        """Invite deletion with validation."""
        invite_to_delete = self.get_object()
        if invite_to_delete.organization not in request.user.organizations:
            raise exceptions.NotFound("You don't belong to the organization this invite is for.")
        invite_to_delete.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
