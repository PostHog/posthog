from typing import Type

from django.db.models import Prefetch
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import create_event_definitions_sql
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventDefinition, TaggedItem
from posthog.permissions import OrganizationMemberPermissions, TeamMemberAccessPermission
from posthog.settings import EE_AVAILABLE

# If EE is enabled, we use ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer


class EventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    is_action = serializers.SerializerMethodField(read_only=True)
    action_id = serializers.IntegerField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    is_calculating = serializers.BooleanField(read_only=True)
    last_calculated_at = serializers.DateTimeField(read_only=True)
    post_to_slack = serializers.BooleanField(default=False)

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
            # Action fields
            "is_action",
            "action_id",
            "is_calculating",
            "last_calculated_at",
            "created_by",
            "post_to_slack",
        )

    def update(self, event_definition: EventDefinition, validated_data):
        raise EnterpriseFeatureException()

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None


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
        # `include_actions`
        #   If true, return both list of event definitions and actions together.
        include_actions = self.request.GET.get("include_actions", None) == "true"

        search = self.request.GET.get("search", None)
        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

        params = {
            "team_id": self.team_id,
            **search_kwargs,
        }

        if EE_AVAILABLE and self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            from ee.models.event_definition import EnterpriseEventDefinition

            # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
            sql = create_event_definitions_sql(include_actions, is_enterprise=True, conditions=search_query)

            ee_event_definitions = EnterpriseEventDefinition.objects.raw(sql, params=params)
            ee_event_definitions_list = ee_event_definitions.prefetch_related(
                Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
            )

            return ee_event_definitions_list

        sql = create_event_definitions_sql(include_actions, is_enterprise=False, conditions=search_query)
        event_definitions_list = EventDefinition.objects.raw(sql, params=params)

        return event_definitions_list

    def get_object(self):
        id = self.kwargs["id"]
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            from ee.models.event_definition import EnterpriseEventDefinition

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
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):
            from ee.api.ee_event_definition import EnterpriseEventDefinitionSerializer

            serializer_class = EnterpriseEventDefinitionSerializer
        return serializer_class
