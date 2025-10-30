import json
from typing import Any, Literal, Optional, cast

from django.core.cache import cache
from django.db.models import Manager
from django.http import HttpResponse

from loginas.utils import is_impersonated_session
from rest_framework import mixins, request, response, serializers, status, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import action
from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature, EventDefinitionType
from posthog.event_usage import report_user_action
from posthog.exceptions import EnterpriseFeatureException
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

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("An event cannot be both hidden and verified")

        return validated_data

    def update(self, event_definition: EventDefinition, validated_data):
        request = self.context.get("request")
        if not (request and request.user.organization.is_feature_available(AvailableFeature.INGESTION_TAXONOMY)):
            raise EnterpriseFeatureException()
        return super().update(event_definition, validated_data)

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

        excluded_properties = self.request.GET.get("excluded_properties")

        if excluded_properties:
            excluded_list = list(set(json.loads(excluded_properties)))
            search_query = search_query + f" AND NOT name = ANY(ARRAY{excluded_list})"

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

    @action(detail=False, methods=["GET"], url_path="typescript", required_scopes=["event_definition:read"])
    def typescript_definitions(self, *args, **kwargs):
        """Generate TypeScript definitions from event schemas"""
        from django.db.models import Q

        from posthog.models import EventSchema

        # System events that users should be able to manually capture
        # These are commonly used in user code and should be typed
        included_system_events = [
            "$pageview",  # Manually captured in SPAs (React Router, Vue Router, etc.)
            "$pageleave",  # Sometimes manually captured alongside $pageview
            "$screen",  # Manually captured in mobile apps (iOS, Android, React Native, Flutter)
        ]

        # Fetch event definitions: either non-system events or explicitly included system events
        event_definitions = (
            EventDefinition.objects.filter(team__project_id=self.project_id)
            .filter(
                Q(name__in=included_system_events)  # Include whitelisted system events
                | ~Q(name__startswith="$")  # Include all non-system events
            )
            .order_by("name")
        )

        # Fetch all event schemas with their property groups
        event_schemas = (
            EventSchema.objects.filter(event_definition__team__project_id=self.project_id)
            .select_related("property_group")
            .prefetch_related("property_group__properties")
        )

        # Build a mapping of event_definition_id -> property group properties
        schema_map = {}
        for event_schema in event_schemas:
            event_id = str(event_schema.event_definition_id)
            if event_id not in schema_map:
                schema_map[event_id] = []
            schema_map[event_id].extend(event_schema.property_group.properties.all())

        # Generate TypeScript definitions
        ts_content = self._generate_typescript(event_definitions, schema_map)

        return HttpResponse(
            ts_content,
            content_type="text/plain; charset=utf-8",
        )

    def _generate_typescript(self, event_definitions, schema_map):
        """Generate complete TypeScript module with type definitions and exports"""
        from datetime import datetime

        output = []
        output.append("/**")
        output.append(" * GENERATED FILE - DO NOT EDIT")
        output.append(" *")
        output.append(" * This file was auto-generated by PostHog")
        output.append(f" * Generated at: {datetime.now().isoformat()}")
        output.append(" *")
        output.append(" * Provides captureTyped() for type-safe events and capture() for flexibility")
        output.append(" */")
        output.append("")
        output.append("import originalPostHog from 'posthog-js'")
        output.append(
            "import type { PostHog as OriginalPostHog, CaptureOptions, CaptureResult, Properties } from 'posthog-js'"
        )
        output.append("")

        # Generate event schemas
        output.append("// Define event schemas")
        output.append("interface EventSchemas {")

        for event_def in event_definitions:
            properties = schema_map.get(str(event_def.id), [])
            # Escape event name for use as object key
            event_name = event_def.name.replace("'", "\\'")

            if not properties:
                output.append(f"    '{event_name}': Record<string, any>")
            else:
                output.append(f"    '{event_name}': {{")
                for prop in properties:
                    ts_type = self._map_property_type(prop.property_type)
                    optional_marker = "" if prop.is_required else "?"
                    output.append(f"        {prop.name}{optional_marker}: {ts_type}")
                output.append("    }")

        output.append("}")
        output.append("")

        # Generate type aliases
        output.append("// Type alias for all valid event names")
        output.append("export type EventName = keyof EventSchemas")
        output.append("")
        output.append("// Type helper to get properties for a specific event (includes additional properties)")
        output.append("export type EventProperties<K extends EventName> = EventSchemas[K] & Record<string, any>")
        output.append("")
        output.append("// Helper type to check if a type requires properties (has required fields)")
        output.append("// eslint-disable-next-line @typescript-eslint/no-empty-object-type")
        output.append("type RequiresProperties<T> = {} extends T ? false : true")
        output.append("")

        # Generate TypedPostHog interface
        output.append("// Enhanced PostHog interface with typed capture")
        output.append("interface TypedPostHog extends Omit<OriginalPostHog, 'capture'> {")
        output.append("    /**")
        output.append("     * Type-safe capture for defined events")
        output.append("     *")
        output.append("     * Note: Additional properties beyond the schema are allowed")
        output.append("     *")
        output.append("     * @example")
        output.append("     * posthog.captureTyped('Product Added', {")
        output.append("     *   product_id: '123',")
        output.append("     *   name: 'Widget',")
        output.append("     *   price: 42,")
        output.append("     *   quantity: 1,")
        output.append("     *   custom_field: 'extra' // additional properties allowed")
        output.append("     * })")
        output.append("     *")
        output.append("     * @example")
        output.append("     * // For events with all optional properties, properties argument is optional")
        output.append("     * posthog.captureTyped('Logged in') // no properties needed")
        output.append("     */")
        output.append("    captureTyped<K extends EventName>(")
        output.append("        event_name: K,")
        output.append("        ...args: RequiresProperties<EventSchemas[K]> extends true")
        output.append("            ? [properties: EventProperties<K>, options?: CaptureOptions]")
        output.append("            : [properties?: EventProperties<K>, options?: CaptureOptions]")
        output.append("    ): CaptureResult | undefined")
        output.append("")
        output.append("    /**")
        output.append("     * Flexible capture for any event (original behavior)")
        output.append("     *")
        output.append("     * Use captureTyped() when you want type safety for defined events.")
        output.append("     * Use capture() when you need flexibility (dynamic events, untyped events, etc.)")
        output.append("     *")
        output.append("     * @example")
        output.append("     * posthog.capture('Custom Event Name', { any: 'data' })")
        output.append("     */")
        output.append(
            "    capture(event_name: string, properties?: Properties | null, options?: CaptureOptions): CaptureResult | undefined"
        )
        output.append("}")
        output.append("")

        # Generate implementation
        output.append("// Create the implementation")
        output.append("const createTypedPostHog = (original: OriginalPostHog): TypedPostHog => {")
        output.append("    // Create the enhanced PostHog object")
        output.append("    const enhanced: TypedPostHog = Object.create(original)")
        output.append("")
        output.append("    // Add captureTyped method")
        output.append(
            "    enhanced.captureTyped = function <K extends EventName>(event_name: K, ...args: any[]): CaptureResult | undefined {"
        )
        output.append("        const [properties, options] = args")
        output.append("        return original.capture(event_name, properties, options)")
        output.append("    }")
        output.append("")
        output.append("    // Keep capture method for untyped/flexible event tracking")
        output.append("    enhanced.capture = function (")
        output.append("        event_name: string,")
        output.append("        properties?: Properties | null,")
        output.append("        options?: CaptureOptions")
        output.append("    ): CaptureResult | undefined {")
        output.append("        return original.capture(event_name, properties, options)")
        output.append("    }")
        output.append("")
        output.append("    // Proxy to delegate all other properties/methods to the original")
        output.append("    return new Proxy(enhanced, {")
        output.append("        get(target, prop) {")
        output.append("            if (prop in target) {")
        output.append("                return (target as any)[prop]")
        output.append("            }")
        output.append("            return (original as any)[prop]")
        output.append("        },")
        output.append("        set(target, prop, value) {")
        output.append("            ;(original as any)[prop] = value")
        output.append("            return true")
        output.append("        },")
        output.append("    })")
        output.append("}")
        output.append("")

        # Generate exports
        output.append("// Create and export the typed instance")
        output.append("const posthog = createTypedPostHog(originalPostHog as OriginalPostHog)")
        output.append("")
        output.append("export default posthog")
        output.append("export { posthog }")
        output.append("export type { EventSchemas, TypedPostHog }")
        output.append("")
        output.append("// Re-export everything else from posthog-js")
        output.append("export * from 'posthog-js'")
        output.append("")
        output.append("/**")
        output.append(" * USAGE GUIDE")
        output.append(" * ===========")
        output.append(" *")
        output.append(" * For type-safe events (recommended):")
        output.append(
            " *   posthog.captureTyped('Product Added', { product_id: '123', name: 'Widget', price: 42, quantity: 1 })"
        )
        output.append(" *")
        output.append(" * For untyped/dynamic events (when you need flexibility):")
        output.append(" *   posthog.capture('Custom Event', { any: 'data' })")
        output.append(" */")

        return "\n".join(output)

    def _map_property_type(self, property_type: str) -> str:
        """Map PostHog property types to TypeScript types"""
        type_map = {
            "String": "string",
            "Numeric": "number",
            "Boolean": "boolean",
            "DateTime": "string | Date",
            "Array": "any[]",
            "Object": "Record<string, any>",
        }
        return type_map.get(property_type, "any")

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
