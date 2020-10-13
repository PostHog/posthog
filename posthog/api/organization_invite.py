from typing import Any, Dict

from django.db.models import QuerySet, query
from django.http.response import Http404
from rest_framework import exceptions, mixins, response, serializers, status, viewsets
from rest_framework_extensions.mixins import NestedViewSetMixin

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
    NestedViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationInviteSerializer
    pagination_class = None
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationInvite.objects.none()
    lookup_field = "id"
    ordering_fields = ["created_by"]
    ordering = ["-created_by"]

    def filter_queryset_by_parents_lookups(self, queryset) -> QuerySet:
        parents_query_dict = self.get_parents_query_dict()
        print(parents_query_dict)
        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise Http404
        else:
            return queryset

        organization_id = self.kwargs["organization_pk"]
        if organization_id == "@current":
            organization_id = self.request.user.organization.id
        return (
            OrganizationInvite.objects.filter(organization_id=organization_id)
            .select_related("created_by")
            .select_related("last_used_by")
            .order_by("-created_at")
        )
