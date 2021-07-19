from distutils.util import strtobool
from typing import Optional, Type, TypeVar

from django.db import connection, models
from django.db.models.query import QuerySet
from rest_framework import filters, mixins, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.api.routing import StructuredViewSetMixin
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import FuzzySearchFilterBackend
from posthog.models import PropertyDefinition
from posthog.permissions import OrganizationMemberPermissions

_MT = TypeVar("_MT", bound=models.Model)


class PropertyDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyDefinition
        fields = (
            "id",
            "name",
            "is_numerical",
            "query_usage_30_day",
        )

    def update(self, property_definition: PropertyDefinition, validated_data):
        raise EnterpriseFeatureException()


class NumericalFilter(filters.BaseFilterBackend):
    def filter_queryset(self, request: Request, queryset: QuerySet[_MT], view: APIView,) -> QuerySet[_MT]:
        param: Optional[str] = request.query_params.get("is_numerical", None)

        if not param:
            return queryset

        parsed_param: bool = strtobool(param)
        return queryset.filter(is_numerical=parsed_param)


class PropertyDefinitionViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PropertyDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    filter_backends = [FuzzySearchFilterBackend]
    search_fields = ["name"]
    search_threshold = 0.15

    def get_queryset(self):
        if True:  # self.request.user.organization.is_feature_available("ingestion_taxonomy"):  # type: ignore
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition
            except ImportError:
                pass
            else:
                properties_to_filter = self.request.GET.get("properties", None)
                if properties_to_filter:
                    names = tuple(properties_to_filter.split(","))
                    name_filter = f"AND name IN %(names)s"
                else:
                    names = ()
                    name_filter = ""

                search = self.request.GET.get("search", None)
                select_criteria = f"*, similarity(name, '{search}')" if bool(search) else "*"
                search_threshold_filter = f"AND name % {search}" if bool(search) else ""
                ee_property_definitions = EnterprisePropertyDefinition.objects.raw(
                    f"""
                    SELECT {select_criteria}
                    FROM ee_enterprisepropertydefinition
                    FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id
                    WHERE team_id = %(team_id)s {name_filter} {search_threshold_filter}
                    ORDER BY name
                    """,
                    params={"team_id": self.request.user.team.id, "names": names},  # type: ignore
                )
                return ee_property_definitions

        return self.filter_queryset_by_parents_lookups(PropertyDefinition.objects.all())

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available("ingestion_taxonomy"):  # type: ignore
            try:
                from ee.api.enterprise_property_definition import EnterprisePropertyDefinitionSerializer
            except ImportError:
                pass
            else:
                serializer_class = EnterprisePropertyDefinitionSerializer  # type: ignore
        return serializer_class

    def get_object(self):
        id = self.kwargs["id"]
        if self.request.user.organization.is_feature_available("ingestion_taxonomy"):  # type: ignore
            try:
                from ee.models.property_definition import EnterprisePropertyDefinition
            except ImportError:
                pass
            else:
                enterprise_property = EnterprisePropertyDefinition.objects.filter(id=id).first()
                if enterprise_property:
                    return enterprise_property
                non_enterprise_property = PropertyDefinition.objects.get(id=id)
                new_enterprise_property = EnterprisePropertyDefinition(
                    propertydefinition_ptr_id=non_enterprise_property.id, description=""
                )
                new_enterprise_property.__dict__.update(non_enterprise_property.__dict__)
                new_enterprise_property.save()
                return new_enterprise_property
        return PropertyDefinition.objects.get(id=id)
