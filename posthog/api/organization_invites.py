from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import exceptions, mixins, response, serializers, status, viewsets

from posthog.api.user import UserSerializer
from posthog.models import Organization, OrganizationInvite, OrganizationMembership


class OrganizationInviteSerializer(serializers.ModelSerializer):
    last_used_by_id = serializers.CharField(source="last_used_by.id", read_only=True)
    last_used_by_email = serializers.CharField(source="last_used_by.email", read_only=True)
    last_used_by_first_name = serializers.CharField(source="last_used_by.first_name", read_only=True)
    created_by_id = serializers.CharField(source="created_by.id", read_only=True)
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
    lookup_field = "id"

    def get_queryset(self) -> QuerySet:
        return (
            OrganizationInvite.objects.filter(organization=self.request.user.organization)
            .select_related("created_by")
            .select_related("last_used_by")
            .order_by("-created_at")
        )

    def destroy(self, request, *args, **kwargs):
        """Invite deletion with validation (admin permissions)."""
        invite_to_delete = self.get_object()
        try:
            if (
                OrganizationMembership.objects.get(user=request.user, organization=request.user.organization).level
                < OrganizationMembership.Level.ADMIN
            ):
                raise exceptions.PermissionDenied({"detail": "You are not permitted to delete organization invites."})
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound({"detail": "User does not exist or does not belong to the organization."})
        invite_to_delete.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
