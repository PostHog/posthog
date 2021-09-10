from typing import Type

from rest_framework import filters, mixins, permissions, serializers, status, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventDefinition
from posthog.permissions import OrganizationMemberPermissions


class EventDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventDefinition
        fields = (
            "id",
            "name",
            "volume_30_day",
            "query_usage_30_day",
        )

    def update(self, event_definition: EventDefinition, validated_data):
        raise EnterpriseFeatureException()


class EventDefinitionViewSet(
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]
    ordering = "name"
    search_fields = ["name"]

    def get_queryset(self):
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.event_definition import EnterpriseEventDefinition
            except ImportError:
                pass
            else:
                search = self.request.GET.get("search", None)
                search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)
                ee_event_definitions = EnterpriseEventDefinition.objects.raw(
                    f"""
                    SELECT *
                    FROM ee_enterpriseeventdefinition
                    FULL OUTER JOIN posthog_eventdefinition ON posthog_eventdefinition.id=ee_enterpriseeventdefinition.eventdefinition_ptr_id
                    WHERE team_id = %(team_id)s {search_query}
                    ORDER BY name
                    """,
                    params={"team_id": self.request.user.team.id, **search_kwargs},  # type: ignore
                )
                return ee_event_definitions

        return self.filter_queryset_by_parents_lookups(EventDefinition.objects.all()).order_by(self.ordering)

    def get_object(self):
        id = self.kwargs["id"]
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.event_definition import EnterpriseEventDefinition
            except ImportError:
                pass
            else:
                enterprise_event = EnterpriseEventDefinition.objects.filter(id=id).first()
                if enterprise_event:
                    return enterprise_event
                non_enterprise_event = EventDefinition.objects.get(id=id)
                new_enterprise_event = EnterpriseEventDefinition(
                    eventdefinition_ptr_id=non_enterprise_event.id, description=""
                )
                new_enterprise_event.__dict__.update(non_enterprise_event.__dict__)
                new_enterprise_event.save()
                return new_enterprise_event
        return EventDefinition.objects.get(id=id)

    def get_serializer_class(self) -> Type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.api.enterprise_event_definition import EnterpriseEventDefinitionSerializer
            except ImportError:
                pass
            else:
                serializer_class = EnterpriseEventDefinitionSerializer  # type: ignore
        return serializer_class
