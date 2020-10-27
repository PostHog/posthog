from typing import Any, Dict

from django.db.models import QuerySet
from django.db.models.base import Model
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework_extensions.mixins import NestedViewSetMixin

from posthog.models import OrganizationInvite
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    created_by_first_name = serializers.CharField(source="created_by.first_name", read_only=True)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
            "created_by_id",
            "created_by_email",
            "created_by_first_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
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
    NestedViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationInviteSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationInvite.objects.all()
    lookup_field = "id"
    ordering = "-created_at"

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(super().get_queryset()).order_by(self.ordering)

    def filter_queryset_by_parents_lookups(self, queryset) -> QuerySet:
        parents_query_dict = self.get_parents_query_dict()
        if parents_query_dict:
            if parents_query_dict["organization_id"] == "@current":
                parents_query_dict["organization_id"] = self.request.user.organization.id
            try:
                return queryset.filter(**parents_query_dict).select_related("created_by")
            except ValueError:
                raise exceptions.NotFound()
        else:
            return queryset
