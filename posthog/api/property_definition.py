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


def is_pg_trgm_installed():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_trgm'")
            row = cursor.fetchone()
            has_extension = bool(row) and bool(row[0])
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    i.relname as index_name
                FROM
                    pg_class i,
                    pg_index ix
                WHERE
                    i.oid = ix.indexrelid
                    and i.relname = 'index_property_definition_name';
            """
            )
            row = cursor.fetchone()
            has_index = bool(row) and bool(row[0])
        return has_extension and has_index
    except BaseException:
        return False


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
    ordering = "name"
    filter_backends = [NumericalFilter, filters.OrderingFilter, FuzzySearchFilterBackend]
    search_fields = ["name"]
    search_threshold = 0.15
    ordering_fields = ["name", "volume_30_day", "query_usage_30_day"]  # User can filter by any of these attributes
    # Ordering below ensures more relevant results are returned first, particularly relevant for initial fetch
    # When a ?search= filter is applied, the `similarity` will take precedence (i.e. we'll
    # return items first that best match the query)
    ordering = ["-query_usage_30_day", "-volume_30_day", "name"]

    def get_queryset(self):
        if self.request.user.organization.is_feature_available("ingestion_taxonomy"):  # type: ignore
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
                    name_filter = ""
                    names = ()
                ee_property_definitions = EnterprisePropertyDefinition.objects.raw(
                    f"""
                    SELECT *
                    FROM ee_enterprisepropertydefinition
                    FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id
                    WHERE team_id = %(team_id)s {name_filter}
                    ORDER BY name
                    """,
                    params={"team_id": self.request.user.team.id, "names": names},  # type: ignore
                )
                return ee_property_definitions
        objects = PropertyDefinition.objects
        if self.pg_trgm_installed and "search" in self.request.query_params:
            objects = objects.filter(name__trigram_similar=self.request.query_params["search"])
        else:
            objects = objects.all()
        return self.filter_queryset_by_parents_lookups(objects)

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
