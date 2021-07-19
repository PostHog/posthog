from typing import Type

from django.db.models import Q
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.exceptions import EnterpriseFeatureException
from posthog.models import PropertyDefinition
from posthog.permissions import OrganizationMemberPermissions


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

    def get_queryset(self):
        # input query
        search_string = self.request.GET.get("search", None)
        # for EE raw SQL
        search_filter = ""
        search_kwargs = {}
        # for django ORM
        search_filter_query = Q()

        if search_string:
            search_parts = search_string.split(" ")
            search_filter_parts = []
            for index, part in enumerate(search_parts):
                search_filter_parts.append(f"name ILIKE %(search{index})s")
                search_kwargs[f"search{index}"] = f"%{part}%"
                search_filter_query = search_filter_query & Q(name__contains=part)
            if len(search_filter_parts) > 0:
                search_filter = " AND ".join(search_filter_parts)

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

                and_search_filter = f"AND {search_filter}" if search_filter else ""

                ee_property_definitions = EnterprisePropertyDefinition.objects.raw(
                    f"""
                    SELECT *
                    FROM ee_enterprisepropertydefinition
                    FULL OUTER JOIN posthog_propertydefinition ON posthog_propertydefinition.id=ee_enterprisepropertydefinition.propertydefinition_ptr_id
                    WHERE team_id = %(team_id)s {name_filter} {and_search_filter}
                    ORDER BY name
                    """,
                    params={"team_id": self.request.user.team.id, "names": names, **search_kwargs},  # type: ignore
                )
                return ee_property_definitions

        if search_filter_query:
            objects = PropertyDefinition.objects.filter(search_filter_query)
        else:
            objects = PropertyDefinition.objects.all()

        return self.filter_queryset_by_parents_lookups(objects).order_by(self.ordering)

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
