from typing import Any, Literal, Optional, cast

from django.core.cache import cache
from django.db.models import Manager

import orjson
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import mixins, request, response, serializers, status, viewsets

from posthog.api.event_definition_generators.base import EventDefinitionGenerator
from posthog.api.event_definition_generators.golang import GolangGenerator
from posthog.api.event_definition_generators.python import PythonGenerator
from posthog.api.event_definition_generators.typescript import TypeScriptGenerator
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.client import sync_execute
from posthog.constants import EventDefinitionType
from posthog.event_usage import report_user_action
from posthog.filters import TermSearchFilterBackend, term_search_filter_sql
from posthog.models import EventDefinition, Team
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.user import User
from posthog.models.utils import UUIDT
from posthog.settings import EE_AVAILABLE
from posthog.utils import get_safe_cache, relative_date_parse

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

    def validate_name(self, value):
        # For creation, check if event definition with this name already exists
        if not self.instance:  # Only for creation, not updates
            view = self.context.get("view")
            if view:
                existing = EventDefinition.objects.filter(team_id=view.team_id, name=value).exists()
                if existing:
                    raise serializers.ValidationError(f"Event definition with name '{value}' already exists")
        return value

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("An event cannot be both hidden and verified")

        return validated_data

    def create(self, validated_data):
        request = self.context.get("request")
        # Get viewset from context to access organization_id and team_id
        view = self.context.get("view")
        if not view:
            raise serializers.ValidationError("View context is required")

        # Type narrowing for mypy
        assert view is not None

        validated_data["team_id"] = view.team_id
        validated_data["project_id"] = view.project_id
        # Set timestamps to None - will be populated when first real event is ingested
        validated_data["created_at"] = None
        validated_data["last_seen_at"] = None

        # Remove fields that don't exist on the model
        validated_data.pop("post_to_slack", None)

        event_definition = super().create(validated_data)

        # Report user action for analytics
        if request and request.user:
            report_user_action(
                cast(User, request.user),
                "event definition created",
                {"name": event_definition.name},
            )

        return event_definition

    def get_is_action(self, obj):
        return hasattr(obj, "action_id") and obj.action_id is not None


@extend_schema(tags=["core"])
class EventDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    TaggedItemViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
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

        event_definition_object_manager: Manager
        if EE_AVAILABLE:
            from ee.models.event_definition import EnterpriseEventDefinition

            event_definition_object_manager = EnterpriseEventDefinition.objects
        else:
            event_definition_object_manager = EventDefinition.objects

        exclude_hidden = self.request.GET.get("exclude_hidden", "false").lower() == "true"
        if exclude_hidden and EE_AVAILABLE:
            search_query = search_query + " AND (hidden IS NULL OR hidden = false)"

        excluded_properties = self.request.GET.get("excluded_properties")

        if excluded_properties:
            excluded_list = list(set(orjson.loads(excluded_properties)))
            search_query = search_query + " AND NOT name = ANY(%(excluded_list)s)"
            params["excluded_list"] = excluded_list

        sql = create_event_definitions_sql(
            event_type,
            is_enterprise=EE_AVAILABLE,
            conditions=search_query,
            order_expressions=order_expressions,
        )
        queryset = event_definition_object_manager.raw(sql, params=params)

        # Apply tags filter if provided
        tags = self.request.GET.get("tags")
        if tags:
            try:
                tags_list = orjson.loads(tags)
                if tags_list:
                    # Convert raw queryset to regular queryset for filtering
                    ids = [obj.id for obj in queryset]
                    queryset = event_definition_object_manager.filter(  # type: ignore[assignment]
                        id__in=ids, tagged_items__tag__name__in=tags_list
                    ).distinct()
            except (orjson.JSONDecodeError, TypeError):
                # If the JSON is invalid, ignore the filter
                pass

        return queryset

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
        if EE_AVAILABLE:
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
        if EE_AVAILABLE:
            from ee.api.ee_event_definition import EnterpriseEventDefinitionSerializer

            serializer_class = EnterpriseEventDefinitionSerializer  # type: ignore
        return serializer_class

    def perform_create(self, serializer):
        """Handle context and side effects for event definition creation."""
        user = cast(User, self.request.user)

        # Build save kwargs - only include updated_by for enterprise
        save_kwargs: dict[str, Any] = {
            "team_id": self.team_id,
            "project_id": self.project_id,
            "created_at": None,  # Will be populated when first real event is ingested
            "last_seen_at": None,
        }

        # Add updated_by only for EnterpriseEventDefinition
        if hasattr(serializer.Meta.model, "updated_by"):
            save_kwargs["updated_by"] = user

        event_definition = serializer.save(**save_kwargs)

        # Log activity for audit trail
        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=user,
            was_impersonated=is_impersonated_session(self.request),
            item_id=str(event_definition.id),
            scope="EventDefinition",
            activity="created",
            detail=Detail(name=event_definition.name, changes=None),
        )

    def perform_update(self, serializer):
        """Handle context and side effects for event definition updates."""
        user = cast(User, self.request.user)
        instance = serializer.instance

        # Capture before state for activity logging
        before_state = {k: instance.__dict__[k] for k in serializer.validated_data.keys() if k in instance.__dict__}
        # Handle tags None -> [] to avoid spurious activity logs
        if "tags" not in before_state or before_state["tags"] is None:
            before_state["tags"] = []

        # Only pass updated_by for EnterpriseEventDefinition
        save_kwargs: dict[str, Any] = {}
        if hasattr(instance, "updated_by"):
            save_kwargs["updated_by"] = user

        event_definition = serializer.save(**save_kwargs)

        # Log activity for audit trail
        from posthog.models.activity_logging.activity_log import dict_changes_between

        changes = dict_changes_between("EventDefinition", before_state, serializer.validated_data, True)

        log_activity(
            organization_id=None,
            team_id=self.team_id,
            user=user,
            item_id=str(event_definition.id),
            scope="EventDefinition",
            activity="changed",
            was_impersonated=is_impersonated_session(self.request),
            detail=Detail(name=str(event_definition.name), changes=changes),
        )

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

    @action(detail=False, methods=["GET"], url_path="typescript", required_scopes=["event_definition:read"])
    def typescript_definitions(self, *args, **kwargs):
        return self._generate_definitions(TypeScriptGenerator())

    @action(detail=False, methods=["GET"], url_path="golang", required_scopes=["event_definition:read"])
    def golang_definitions(self, *args, **kwargs):
        return self._generate_definitions(GolangGenerator())

    @action(detail=False, methods=["GET"], url_path="python", required_scopes=["event_definition:read"])
    def python_definitions(self, *args, **kwargs):
        return self._generate_definitions(PythonGenerator())

    def _generate_definitions(self, generator: EventDefinitionGenerator) -> response.Response:
        event_definitions, schema_map = generator.fetch_event_definitions_and_schemas(self.project_id)

        schema_hash = generator.calculate_schema_hash(event_definitions, schema_map)
        content = generator.generate(event_definitions, schema_map)

        generator.record_report_generation(
            self.request.user,
            self.team_id,
            self.project_id,
        )

        return response.Response(
            {
                "content": content,
                "event_count": len(event_definitions),
                "schema_hash": schema_hash,
                "generator_version": generator.generator_version(),
            }
        )

    @action(detail=True, methods=["GET"], url_path="metrics")
    def metrics_totals(self, *args, **kwargs):
        instance: EventDefinition = self.get_object()

        query_usage_30_day = fetch_30day_event_queries(
            team=self.team,
            event_name=instance.name,
        )

        return response.Response(
            {
                "query_usage_30_day": query_usage_30_day,
            }
        )


def fetch_30day_event_queries(
    team: Team,
    event_name: str,
) -> int:
    """
    Calculate the total number of views for a specific event
    """
    cache_key = f"event_definition:event_views_total:{team.pk}:{event_name}"
    cached_result = get_safe_cache(cache_key)
    if cached_result is not None:
        return cached_result

    clickhouse_kwargs: dict[str, Any] = {
        "team_id": team.pk,
        "app_source": "event_usage",
        "metric_name": "viewed",
        "instance_id": f"event:{event_name}",
        "after": relative_date_parse("30d", team.timezone_info).strftime("%Y-%m-%dT%H:%M:%S"),
    }

    clickhouse_query = f"""
        SELECT
            sum(count) as count
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND timestamp >= toDateTime64(%(after)s, 6)
        AND instance_id = %(instance_id)s
        AND metric_name = %(metric_name)s
    """

    results = sync_execute(clickhouse_query, clickhouse_kwargs)

    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    total = results[0][0] if results else 0

    cache.set(cache_key, total, timeout=24 * 60 * 60)  # 24 hours

    return total
