from distutils.util import strtobool
from typing import Optional, TypeVar

from django.db import models
from django.db.models.query import QuerySet
from rest_framework import filters, mixins, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import PropertyDefinition
from posthog.permissions import OrganizationMemberPermissions

_MT = TypeVar("_MT", bound=models.Model)


class NumericalFilter(filters.BaseFilterBackend):
    def filter_queryset(self, request: Request, queryset: QuerySet[_MT], view: APIView) -> QuerySet[_MT]:
        param: Optional[str] = request.query_params.get("is_numerical", None)

        if not param:
            return queryset

        parsed_param: bool = strtobool(param)
        return queryset.filter(is_numerical=parsed_param)


class PropertyDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyDefinition
        fields = (
            "id",
            "name",
            "is_numerical",
            "volume_30_day",
            "query_usage_30_day",
        )


class PropertyDefinitionViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet,
):
    serializer_class = PropertyDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    ordering = "name"
    filter_backends = [NumericalFilter, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "volume_30_day", "query_usage_30_day"]  # User can filter by any of these attributes
    ordering = [
        "-query_usage_30_day",
        "-volume_30_day",
        "name",
    ]  # Ordering below ensures more relevant results are returned first, particularly relevant for initial fetch

    def get_queryset(self):
        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all())
