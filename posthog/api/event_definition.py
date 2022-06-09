from itertools import chain
from typing import Type

from django.db.models import BooleanField, Case, Prefetch, Q, Value, When
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import check_definition_ids_inclusion_field_sql
from posthog.constants import AvailableFeature
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import Action, EventDefinition, TaggedItem
from posthog.permissions import OrganizationMemberPermissions, TeamMemberAccessPermission


# If EE is enabled, we use ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer
class EventDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    is_action = serializers.SerializerMethodField(read_only=True)

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
            "is_action",
        )

    def update(self, event_definition: EventDefinition, validated_data):
        raise EnterpriseFeatureException()

    def get_is_action(self, obj):
        return isinstance(obj, Action)


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
        # `order_ids_first`
        #   Any definition ids passed into the `order_ids_first` parameter will make sure that those definitions
        #   appear at the beginning of the list of definitions. This is used in the app when we want specific
        #   definitions to show at the top of a table so that they can be highlighted (i.e. viewing an individual
        #   definition's context).
        #
        #   Note that ids included in `order_ids_first` will override the same ids in `excluded_ids`.
        order_ids_first_field, order_ids_first = check_definition_ids_inclusion_field_sql(
            raw_included_definition_ids=self.request.GET.get("order_ids_first", None),
            is_property=False,
            named_key="order_ids_first",
        )

        # `excluded_ids`
        #   Any definitions ids specified in the `excluded_ids` parameter will be omitted from the results.
        excluded_ids_field, excluded_ids = check_definition_ids_inclusion_field_sql(
            raw_included_definition_ids=self.request.GET.get("excluded_ids", None),
            is_property=False,
            named_key="excluded_ids",
        )

        # `include_actions`
        #   If true, return both list of event definitions and actions together.
        include_actions = self.request.GET.get("include_actions", None)
        actions_list = Action.objects.none()
        if include_actions:
            actions_list = Action.objects.filter(deleted=False)

        if self.request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY):  # type: ignore
            try:
                from ee.models.event_definition import EnterpriseEventDefinition
            except ImportError:
                pass
            else:
                search = self.request.GET.get("search", None)
                search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

                params = {
                    "team_id": self.team_id,
                    "order_ids_first": order_ids_first,
                    "excluded_ids": excluded_ids,
                    **search_kwargs,
                }

                # Prevent fetching deprecated `tags` field. Tags are separately fetched in TaggedItemSerializerMixin
                event_definition_fields = ", ".join(
                    [f'"{f.column}"' for f in EnterpriseEventDefinition._meta.get_fields() if hasattr(f, "column") and f.column != "tags"]  # type: ignore
                )

                ee_event_definitions = EnterpriseEventDefinition.objects.raw(
                    f"""
                    SELECT {event_definition_fields},
                           {order_ids_first_field} AS is_ordered_first
                    FROM ee_enterpriseeventdefinition
                    FULL OUTER JOIN posthog_eventdefinition ON posthog_eventdefinition.id=ee_enterpriseeventdefinition.eventdefinition_ptr_id
                    WHERE team_id = %(team_id)s AND (
                        {order_ids_first_field} = true
                        OR {excluded_ids_field} = false
                    ) {search_query}
                    ORDER BY is_ordered_first DESC, query_usage_30_day DESC NULLS LAST, last_seen_at DESC NULLS LAST, name ASC
                    """,
                    params=params,
                )
                ee_event_definitions_list = ee_event_definitions.prefetch_related(
                    Prefetch(
                        "tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"
                    )
                )

                return list(chain(actions_list, ee_event_definitions_list))

        event_definitions_list = (
            self.filter_queryset_by_parents_lookups(EventDefinition.objects.all())
            .annotate(
                is_ordered_first=Case(
                    When(id__in=order_ids_first, then=Value(True)), default=Value(False), output_field=BooleanField()
                )
            )
            .annotate(
                is_not_excluded_event=Case(
                    When(id__in=excluded_ids, then=Value(True)), default=Value(False), output_field=BooleanField()
                )
            )
            .filter(Q(is_ordered_first=True) | Q(is_not_excluded_event=False))
            .order_by("-is_ordered_first", "name")
        )

        return list(chain(actions_list, event_definitions_list))

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
