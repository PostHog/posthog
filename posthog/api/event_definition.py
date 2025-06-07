from typing import Any, Literal, cast, Optional

from django.db.models import Manager
from loginas.utils import is_impersonated_session
from rest_framework import mixins, request, response, serializers, status, viewsets
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.constants import AvailableFeature, EventDefinitionType
from posthog.event_usage import report_user_action
from posthog.exceptions import EnterpriseFeatureException
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventDefinition
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.user import User
from posthog.models.utils import UUIDT
from posthog.settings import EE_AVAILABLE

# If EE is enabled, we use ee.api.ee_event_definition.EnterpriseEventDefinitionSerializer


def create_event_definitions_sql(
    event_type: EventDefinitionType,
    is_enterprise: bool = False,
    conditions: str = "",
    order_expressions: Optional[list[tuple[str, Literal["ASC", "DESC"]]]] = None,
) -> str:
    if order_expressions is None:
        order_expressions = []
    if is_enterprise:
        from ee.models import EnterpriseEventDefinition

        ee_model = EnterpriseEventDefinition
    else:
        # telling mypy to ignore this...
        # it's fine to assign EventDefinition
        ee_model = EventDefinition  # type: ignore

    event_definition_fields = {
        f'"{f.column}"'
        for f in ee_model._meta.get_fields()
        if hasattr(f, "column") and f.column not in ["deprecated_tags", "tags"]
    }

    enterprise_join = (
        "FULL OUTER JOIN ee_enterpriseeventdefinition ON posthog_eventdefinition.id=ee_enterpriseeventdefinition.eventdefinition_ptr_id"
        if is_enterprise
        else ""
    )

    if event_type == EventDefinitionType.EVENT_CUSTOM:
        conditions += " AND posthog_eventdefinition.name NOT LIKE %(is_posthog_event)s"
    if event_type == EventDefinitionType.EVENT_POSTHOG:
        conditions += " AND posthog_eventdefinition.name LIKE %(is_posthog_event)s"

    additional_ordering = []
    for order_expression, order_direction in order_expressions:
        if order_expression:
            additional_ordering.append(
                f"{order_expression} {order_direction} NULLS {'FIRST' if order_direction == 'ASC' else 'LAST'}"
            )

    return f"""
            SELECT {",".join(event_definition_fields)}
            FROM posthog_eventdefinition
            {enterprise_join}
            WHERE (project_id = %(project_id)s OR (project_id IS NULL AND team_id = %(project_id)s))
            {conditions}
            ORDER BY {",".join(additional_ordering)}
        """


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

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("An event cannot be both hidden and verified")

        return validated_data

    def update(self, event_definition: EventDefinition, validated_data):
        raise EnterpriseFeatureException()

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None


class EventDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    TaggedItemViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "event_definition"
    serializer_class = EventDefinitionSerializer
    lookup_field = "id"
    filter_backends = [TermSearchFilterBackend]
    queryset = EventDefinition.objects.all()

    search_fields = ["name"]
    ordering_fields = ["name", "last_seen_at"]

    def dangerously_get_queryset(self):
        # `type` = 'all' | 'event' | 'action_event'
        # Allows this endpoint to return lists of event definitions, actions, or both.
        event_type = EventDefinitionType(self.request.GET.get("event_type", EventDefinitionType.EVENT))

        search = self.request.GET.get("search", None)
        search_query, search_kwargs = term_search_filter_sql(self.search_fields, search)

        params = {"project_id": self.project_id, "is_posthog_event": "$%", **search_kwargs}
        order_expressions = self._ordering_params_from_request()

        ingestion_taxonomy_is_available = self.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)
        is_enterprise = EE_AVAILABLE and ingestion_taxonomy_is_available

        event_definition_object_manager: Manager
        if is_enterprise:
            from ee.models.event_definition import EnterpriseEventDefinition

            event_definition_object_manager = EnterpriseEventDefinition.objects

        else:
            event_definition_object_manager = EventDefinition.objects

        exclude_hidden = self.request.GET.get("exclude_hidden", "false").lower() == "true"
        if exclude_hidden and is_enterprise:
            search_query = search_query + " AND (hidden IS NULL OR hidden = false)"

        sql = create_event_definitions_sql(
            event_type,
            is_enterprise=is_enterprise,
            conditions=search_query,
            order_expressions=order_expressions,
        )
        return event_definition_object_manager.raw(sql, params=params)

    def _ordering_params_from_request(
        self,
    ) -> list[tuple[str, Literal["ASC", "DESC"]]]:
        order_direction: Literal["ASC", "DESC"]

        results = []

        # API client can send more than one ordering
        orderings = self.request.GET.getlist("ordering")

        for ordering in orderings:
            if ordering and ordering.replace("-", "") in ["name", "last_seen_at", "last_seen_at::date"]:
                order = ordering.replace("-", "")
                if "-" in ordering:
                    order_direction = "DESC"
                else:
                    order_direction = "ASC"

                results.append((order, order_direction))

        if not results:
            results = [("last_seen_at::date", "DESC"), ("name", "ASC")]

        return results

    def dangerously_get_object(self):
        id = self.kwargs["id"]
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(  # type: ignore
            AvailableFeature.INGESTION_TAXONOMY
        ):
            from ee.models.event_definition import EnterpriseEventDefinition

            enterprise_event = EnterpriseEventDefinition.objects.filter(id=id, team__project_id=self.project_id).first()
            if enterprise_event:
                return enterprise_event

            non_enterprise_event = EventDefinition.objects.get(id=id, team__project_id=self.project_id)
            new_enterprise_event = EnterpriseEventDefinition(
                eventdefinition_ptr_id=non_enterprise_event.id, description=""
            )
            new_enterprise_event.__dict__.update(non_enterprise_event.__dict__)
            new_enterprise_event.save()
            return new_enterprise_event

        return EventDefinition.objects.get(id=id, team__project_id=self.project_id)

    def get_serializer_class(self) -> type[serializers.ModelSerializer]:
        serializer_class = self.serializer_class
        if EE_AVAILABLE and self.request.user.organization.is_feature_available(  # type: ignore
            AvailableFeature.INGESTION_TAXONOMY
        ):
            from ee.api.ee_event_definition import EnterpriseEventDefinitionSerializer

            serializer_class = EnterpriseEventDefinitionSerializer  # type: ignore
        return serializer_class

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: EventDefinition = self.get_object()
        instance_id: str = str(instance.id)
        self.perform_destroy(instance)
        # Casting, since an anonymous use CANNOT access this endpoint
        report_user_action(
            cast(User, request.user),
            "event definition deleted",
            {"name": instance.name},
        )
        user = cast(User, request.user)
        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=user,
            was_impersonated=is_impersonated_session(request),
            item_id=instance_id,
            scope="EventDefinition",
            activity="deleted",
            detail=Detail(name=cast(str, instance.name), changes=None),
        )
        return response.Response(status=status.HTTP_204_NO_CONTENT)
