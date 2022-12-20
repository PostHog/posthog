from typing import Literal, Tuple, Type

from django.db.models import Manager, Prefetch
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import create_event_definitions_sql
from posthog.constants import AvailableFeature, EventDefinitionType
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
    last_updated_at = serializers.DateTimeField(read_only=True)
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
            "last_updated_at",
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
    permission_classes = [
        permissions.IsAuthenticated,
        OrganizationMemberPermissions,
        TeamMemberAccessPermission,
    ]
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]

    search_fields = ["name"]
    ordering_fields = ["volume_30_day", "query_usage_30_day", "name"]

    def get_queryset(self):
        # `type` = 'all' | 'event' | 'action_event'
        # Allows this endpoint to return lists of event definitions, actions, or both.
        event_type = EventDefinitionType(self.request.GET.get("event_type", EventDefinitionType.EVENT))

        search = self.request.GET.get("search", None)
        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

        params = {"team_id": self.team_id, "is_posthog_event": "$%", **search_kwargs}
        order, order_direction = self._ordering_params_from_request()

        ingestion_taxonomy_is_available = self.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)
        is_enterprise = EE_AVAILABLE and ingestion_taxonomy_is_available

        event_definition_object_manager: Manager
        if is_enterprise:
            from ee.models.event_definition import EnterpriseEventDefinition

            event_definition_object_manager = EnterpriseEventDefinition.objects.prefetch_related(
                Prefetch(
                    "tagged_items",
                    queryset=TaggedItem.objects.select_related("tag"),
                    to_attr="prefetched_tags",
                )
            )
        else:
            event_definition_object_manager = EventDefinition.objects

        sql = create_event_definitions_sql(
            event_type,
            is_enterprise=is_enterprise,
            conditions=search_query,
            order=order,
            direction=order_direction,
        )
        return event_definition_object_manager.raw(sql, params=params)

    def _ordering_params_from_request(
        self,
    ) -> Tuple[str, Literal["ASC", "DESC"]]:
        order_direction: Literal["ASC", "DESC"]
        ordering = self.request.GET.get("ordering")

        if ordering and ordering.replace("-", "") in self.ordering_fields:
            order = ordering.replace("-", "")
            if "-" in ordering:
                order_direction = "DESC"
            else:
                order_direction = "ASC"
        else:
            order = "volume_30_day"
            order_direction = "DESC"

        return order, order_direction

    def get_object(self):
        id = self.kwargs["id"]
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
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
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            from ee.api.ee_event_definition import EnterpriseEventDefinitionSerializer

            serializer_class = EnterpriseEventDefinitionSerializer  # type: ignore
        return serializer_class
