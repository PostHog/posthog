from typing import Type

from django.db.models import BooleanField, Case, Prefetch, Q, Value, When
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import check_definition_ids_inclusion_field_sql
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventDefinition, TaggedItem
from posthog.permissions import OrganizationMemberPermissions, TeamMemberAccessPermission


# If EE is enabled, we use ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer
class EventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = EventDefinition
        fields = (
            "id",
            "name",
            "volume_30_day",
            "query_usage_30_day",
            "created_at",
            "last_seen_at",
            "tags",
        )

    def update(self, event_definition: EventDefinition, validated_data):
        raise EnterpriseFeatureException()


class EventDefinitionViewSet(
    TaggedItemViewSetMixin,
    StructuredViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EventDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions, TeamMemberAccessPermission]
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]
    search_fields = ["name"]

    def get_queryset(self):
        # Include by id
        included_event_ids_field, included_event_ids = check_definition_ids_inclusion_field_sql(
            included_definition_ids=self.request.GET.get("included_event_ids", None), is_property=False
        )

        # Exclude by id
        excluded_event_ids_field, excluded_event_ids = check_definition_ids_inclusion_field_sql(
            included_definition_ids=self.request.GET.get("excluded_event_ids", None), is_property=False
        )

        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.event_definition import EnterpriseEventDefinition
            except ImportError:
                pass
            else:
                search = self.request.GET.get("search", None)
                search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

                # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
                event_definition_fields = ", ".join(
                    [f'"{f.column}"' for f in EnterpriseEventDefinition._meta.get_fields() if hasattr(f, "column") and f.column != "tags"]  # type: ignore
                )

                ee_event_definitions = EnterpriseEventDefinition.objects.raw(
                    f"""
                    SELECT {event_definition_fields},
                           {included_event_ids_field} AS is_included_event,
                           {excluded_event_ids_field} AS is_not_excluded_event
                    FROM ee_enterpriseeventdefinition
                    FULL OUTER JOIN posthog_eventdefinition ON posthog_eventdefinition.id=ee_enterpriseeventdefinition.eventdefinition_ptr_id
                    WHERE team_id = %(team_id)s AND (
                        {excluded_event_ids_field} = false
                        OR {included_event_ids_field} = true
                    ) {search_query}
                    ORDER BY is_included_event DESC, query_usage_30_day DESC NULLS LAST, last_seen_at DESC NULLS LAST, name ASC
                    """,
                    params={"team_id": self.team_id, **search_kwargs},
                )
                return ee_event_definitions.prefetch_related(
                    Prefetch(
                        "tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"
                    )
                )

        return (
            self.filter_queryset_by_parents_lookups(EventDefinition.objects.all())
            .annotate(
                is_included_event=Case(
                    When(id__in=included_event_ids, then=Value(True)), default=Value(False), output_field=BooleanField()
                )
            )
            .annotate(
                is_not_excluded_event=Case(
                    When(id__in=excluded_event_ids, then=Value(True)), default=Value(False), output_field=BooleanField()
                )
            )
            .filter(Q(is_not_excluded_event=False) | Q(is_included_event=True))
            .order_by("-is_included_event", "name")
        )

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
                from ee.api.ee_event_definition import EnterpriseEventDefinitionSerializer
            except ImportError:
                pass
            else:
                serializer_class = EnterpriseEventDefinitionSerializer  # type: ignore
        return serializer_class
