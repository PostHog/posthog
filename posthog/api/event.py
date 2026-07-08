import json
import time
import uuid
import random
import urllib
import builtins
import dataclasses
from datetime import datetime
from typing import Any, Iterator, List, Optional, Union, cast  # noqa: UP035

from django.conf import settings
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from opentelemetry import trace
from prometheus_client import Counter
from rest_framework import mixins, request, response, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.renderers import BaseRenderer
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS
from posthog.hogql.property_utils import create_property_conditions
from posthog.hogql.query import execute_hogql_query

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.event_usage import get_request_analytics_properties
from posthog.exceptions_capture import capture_exception
from posthog.models import Element, Person, PropertyDefinition, User
from posthog.models.event.legacy_events_query import LegacyEventsListQuery, get_one_event
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    EventValuesBurstThrottle,
    EventValuesSustainedThrottle,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.utils import convert_property_value, flatten, refresh_requested_by_client, relative_date_parse

tracer = trace.get_tracer(__name__)

EVENT_VALUES_COUNTER = Counter(
    "posthog_event_values_request",
    "Requests to the events/values endpoint",
    labelnames=["has_event_name", "auth"],
)

QUERY_DEFAULT_EXPORT_LIMIT = 1_000
EVENT_LIST_MAX_LIMIT = 1_000


# Legacy property-filter keys the frontend still appends but EventsQuery's schema forbids.
# They are render hints with no filter semantics, so dropping them preserves old behavior. Any
# OTHER unexpected key is left in place so the schema rejects it (fail loud) rather than being
# silently ignored.
_LEGACY_PROPERTY_KEYS_TO_DROP = {"property_type", "property_type_format"}


def _clean_property_node(node: dict) -> dict:
    """Drop legacy render-hint keys from a property filter, recursing into property groups.

    A group node (`{"type": "AND"/"OR", "values": [...]}`) keeps its structure so the runner's
    `property_to_expr` preserves nested AND/OR; only leaf filters are key-filtered.
    """
    values = node.get("values")
    if isinstance(values, list):
        return {"type": node.get("type"), "values": [_clean_property_node(v) for v in values if isinstance(v, dict)]}
    return {k: v for k, v in node.items() if k not in _LEGACY_PROPERTY_KEYS_TO_DROP}


def _iter_leaf_property_filters(properties: "builtins.list[dict] | dict | None") -> Iterator[dict]:
    """Yield the leaf filter dicts in a flat list or a (possibly nested) property group."""
    stack: builtins.list[dict] = []
    if isinstance(properties, dict):
        stack.append(properties)
    elif properties:
        stack.extend(p for p in properties if isinstance(p, dict))
    while stack:
        node = stack.pop()
        values = node.get("values")
        if isinstance(values, list):
            stack.extend(v for v in values if isinstance(v, dict))
        else:
            yield node


@dataclasses.dataclass(frozen=True)
class EventValueQueryParams:
    event_names: list[str]
    is_column: bool
    key: str
    team: Team
    items: Iterator[tuple[str, str | list[object]]]
    value: str | None


class ElementSerializer(serializers.ModelSerializer):
    event = serializers.CharField()

    class Meta:
        model = Element
        fields = [
            "event",
            "text",
            "tag_name",
            "attr_class",
            "href",
            "attr_id",
            "nth_child",
            "nth_of_type",
            "attributes",
            "order",
        ]


class UncountedLimitOffsetPagination(LimitOffsetPagination):
    """
    the events api works with the default LimitOffsetPagination, but the
    results don't have a count, so we need to override the pagination class
    to remove the count from the response schema
    """

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": "http://api.example.org/accounts/?{offset_param}=400&{limit_param}=100".format(
                        offset_param=self.offset_query_param, limit_param=self.limit_query_param
                    ),
                },
                "results": schema,
            },
        }


class EventViewSet(
    TeamAndOrgViewSetMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "query"
    renderer_classes = cast(
        tuple[type[BaseRenderer], ...],
        (*tuple(api_settings.DEFAULT_RENDERER_CLASSES), csvrenderers.PaginatedCSVRenderer),
    )
    serializer_class = ClickhouseEventSerializer
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    pagination_class = UncountedLimitOffsetPagination

    def get_throttles(self):
        if self.action == "values":
            return [EventValuesBurstThrottle(), EventValuesSustainedThrottle()]
        return super().get_throttles()

    def _build_next_url(
        self,
        request: request.Request,
        last_event_timestamp: datetime,
        order_by: list[str],
    ) -> str:
        params = request.GET.dict()
        reverse = "-timestamp" in order_by
        timestamp = last_event_timestamp.astimezone().isoformat()
        if reverse:
            params["before"] = timestamp
        else:
            params["after"] = timestamp
        return request.build_absolute_uri(f"{request.path}?{urllib.parse.urlencode(params)}")

    @extend_schema(
        description="""
        This endpoint allows you to list and filter events.
        It is effectively deprecated and is kept only for backwards compatibility.
        If you ever ask about it you will be advised to not use it...
        If you want to ad-hoc list or aggregate events, use the Query endpoint instead.
        If you want to export all events or many pages of events you should use our CDP/Batch Exports products instead.
        """,
        parameters=[
            OpenApiParameter(
                "event",
                OpenApiTypes.STR,
                description="Filter list by event. For example `user sign up` or `$pageview`.",
            ),
            OpenApiParameter(
                "select",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions to return",
                many=True,
            ),
            OpenApiParameter(
                "where",
                OpenApiTypes.STR,
                description="(Experimental) JSON-serialized array of HogQL expressions that must pass",
                many=True,
            ),
            OpenApiParameter("person_id", OpenApiTypes.INT, description="Filter list by person id."),
            OpenApiParameter(
                "distinct_id",
                OpenApiTypes.INT,
                description="Filter list by distinct id.",
            ),
            OpenApiParameter(
                "before",
                OpenApiTypes.DATETIME,
                description="Only return events with a timestamp before this time. Default: now() + 5 seconds.",
            ),
            OpenApiParameter(
                "after",
                OpenApiTypes.DATETIME,
                description="Only return events with a timestamp after this time. Default: now() - 24 hours.",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="The maximum number of results to return",
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description=(
                    "Allows to skip first offset rows. Will fail for value larger than 100000. "
                    "Read about proper way of paginating: https://posthog.com/docs/api/queries#5-use-timestamp-based-pagination-instead-of-offset"
                ),
                deprecated=True,
            ),
            PropertiesSerializer(required=False),
            OpenApiParameter(
                "include_person",
                OpenApiTypes.BOOL,
                description="Include person details for each event. Default: false.",
            ),
        ],
    )
    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.QUERY)
        try:
            is_csv_request = self.request.accepted_renderer.format == "csv"

            if self.request.GET.get("limit", None):
                limit = int(self.request.GET.get("limit"))  # type: ignore
            elif is_csv_request:
                limit = QUERY_DEFAULT_EXPORT_LIMIT
            else:
                limit = DEFAULT_RETURNED_ROWS

            limit = min(limit, EVENT_LIST_MAX_LIMIT)

            try:
                offset = int(request.GET["offset"]) if request.GET.get("offset") else 0
            except ValueError:
                offset = 0

            team = self.team

            deprecate_offset = (
                settings.PATCH_EVENT_LIST_MAX_OFFSET > 1 or team.id in settings.PATCH_EVENT_LIST_MAX_OFFSET_PER_TEAM
            )
            if settings.PATCH_EVENT_LIST_MAX_OFFSET > 0 or deprecate_offset:
                if offset > 0:
                    time.sleep(1)
                if offset > 50000 and (deprecate_offset or random.random() < 0.01):  # 1% of queries fail
                    raise serializers.ValidationError("Offset is deprecated. Max supported offset value is 50000")

            properties = self._parse_properties_param(request)
            order_by: list[str] = (
                list(json.loads(request.GET["orderBy"])) if request.GET.get("orderBy") else ["-timestamp"]
            )
            order = "DESC" if len(order_by) == 1 and order_by[0] == "-timestamp" else "ASC"

            restricted_context = self._get_restricted_properties_context(request, team)
            self._reject_restricted_property_references(properties, order_by, restricted_context)

            request_user = cast(Optional[User], request.user if request.user.is_authenticated else None)
            query_result, has_more = LegacyEventsListQuery(team, request_user).run(
                limit=limit,
                offset=offset,
                order=order,
                before=request.GET.get("before"),
                after=request.GET.get("after"),
                event=request.GET.get("event"),
                person_id=request.GET.get("person_id"),
                distinct_id=request.GET.get("distinct_id"),
                properties=properties,
                action_id=request.GET.get("action_id"),
            )

            context = {**restricted_context}
            if request.query_params.get("include_person", "").lower() in ("true", "1"):
                context["people"] = self._get_people(query_result, team)

            result = ClickhouseEventSerializer(
                query_result,
                many=True,
                context=context,
            ).data

            next_url: Optional[str] = None
            if not is_csv_request and has_more and query_result:
                next_url = self._build_next_url(request, query_result[-1]["timestamp"], order_by)
            headers = None
            if settings.PATCH_EVENT_LIST_MAX_OFFSET > 0:
                headers = {"X-PostHog-Warn": "https://posthog.com/docs/api/events"}
            elif deprecate_offset and offset:
                headers = {
                    "X-PostHog-Warn": (
                        "offset is deprecated. "
                        "Use: https://posthog.com/docs/api/queries#5-use-timestamp-based-pagination-instead-of-offset"
                    )
                }
            return response.Response({"next": next_url, "results": result}, headers=headers)

        except Exception as ex:
            capture_exception(ex)
            raise

    def _get_people(self, query_result: List[dict], team: Team) -> "dict[str, Person]":  # noqa: UP006
        distinct_ids = list({event["distinct_id"] for event in query_result})
        with personhog_caller_tag("persons/events-api"):
            return get_persons_mapped_by_distinct_id(team.pk, distinct_ids)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter(
                "include_person",
                OpenApiTypes.BOOL,
                description="Include person details for the event. Default: false.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def retrieve(
        self,
        request: request.Request,
        pk: Optional[Union[int, str]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> response.Response:
        if not isinstance(pk, str) or not UUIDT.is_valid_uuid(pk):
            return response.Response(
                {
                    "detail": "Invalid UUID",
                    "code": "invalid",
                    "type": "validation_error",
                },
                status=400,
            )
        tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.QUERY)
        event = get_one_event(self.team, pk)
        if event is None:
            raise NotFound(detail=f"No events exist for event UUID {pk}")

        query_result = [event]
        query_context = {**self._get_restricted_properties_context(request, self.team)}
        if request.query_params.get("include_person", "").lower() in ("true", "1"):
            query_context["people"] = self._get_people(query_result, self.team)

        res = ClickhouseEventSerializer(query_result[0], many=False, context=query_context).data
        return response.Response(res)

    @action(methods=["GET"], detail=False, required_scopes=["query:read"])
    def values(self, request: request.Request, **kwargs) -> response.Response:
        # `/events/values` is hit from every taxonomic property-value picker across the app, so
        # tag by the endpoint name rather than a generic introspection feature — that makes load
        # from this specific path easy to attribute in query log analysis.
        tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.EVENTS_VALUES_API)
        team = self.team

        key = request.GET.get("key")
        if not key:
            raise serializers.ValidationError("You must provide a key")

        event_names = request.GET.getlist("event_name", None)
        has_event_name = bool(event_names and len(event_names) > 0)
        is_personal_api_key = isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication)

        # Reject personal API key requests without event_name filter
        if is_personal_api_key and not has_event_name:
            raise serializers.ValidationError(
                "The event_name parameter is required when using a personal API key. "
                "For queries without event filters, please use the Query endpoint instead: "
                "https://posthog.com/docs/api/query"
            )

        EVENT_VALUES_COUNTER.labels(
            has_event_name=str(has_event_name),
            auth="personal_api_key" if is_personal_api_key else "app",
        ).inc()

        query_params = EventValueQueryParams(
            event_names=event_names,
            is_column=request.GET.get("is_column", "false").lower() == "true",
            key=key,
            team=team,
            items=request.GET.items(),
            value=request.GET.get("value"),
        )

        refresh = refresh_requested_by_client(request)

        if key == "custom_event":
            return self._custom_event_values(query_params)
        else:
            # Check if this property is hidden (enterprise feature) or restricted by field-level access control
            if self._is_property_hidden(key, team) or self._is_property_restricted(key, team):
                return self._return_with_short_cache([], refreshing=False)

            return self._event_property_values(query_params, refresh=refresh)

    def _event_property_values(
        self,
        query_params: EventValueQueryParams,
        refresh: bool | str = False,
    ) -> response.Response:
        from posthog.hogql_queries.property_values_query_runner import (
            CachedPropertyValuesQueryResponse,
            PropertyType,
            PropertyValuesQuery,
            PropertyValuesQueryResponse,
            PropertyValuesQueryRunner,
        )
        from posthog.hogql_queries.query_runner import ExecutionMode, execution_mode_from_refresh

        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="event").time(),
            tracer.start_as_current_span("events_api_event_property_values") as span,
        ):
            span.set_attribute("team_id", query_params.team.pk)
            span.set_attribute("property_key", query_params.key)
            span.set_attribute("is_column", query_params.is_column)
            span.set_attribute("has_value_filter", query_params.value is not None)
            span.set_attribute("event_names_count", len(query_params.event_names) if query_params.event_names else 0)

            property_filters = [
                (param_key, param_value)
                for param_key, param_value in query_params.items
                if param_key.startswith("properties_") and isinstance(param_value, str)
            ]
            span.set_attribute("property_filter_count", len(property_filters))

            if property_filters:
                # Ad-hoc filtered queries are not cached — run directly
                return self._event_property_values_filtered(query_params, property_filters)

            runner = PropertyValuesQueryRunner(
                team=query_params.team,
                query=PropertyValuesQuery(
                    property_type=PropertyType.EVENT,
                    property_key=query_params.key,
                    is_column=query_params.is_column,
                    search_value=query_params.value,
                    event_names=query_params.event_names or None,
                ),
            )
            execution_mode = execution_mode_from_refresh(refresh)
            if execution_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE and not refresh:
                execution_mode = ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
            result = runner.run(execution_mode, analytics_props=get_request_analytics_properties(self.request))
            assert isinstance(result, (PropertyValuesQueryResponse, CachedPropertyValuesQueryResponse))
            is_refreshing = (
                isinstance(result, CachedPropertyValuesQueryResponse)
                and result.query_status is not None
                and not result.query_status.complete
            )
            span.set_attribute("result_count", len(result.results))
            span.set_attribute("is_refreshing", is_refreshing)
            return self._return_with_short_cache(
                [item.model_dump(exclude_none=True) for item in result.results], refreshing=is_refreshing
            )

    def _event_property_values_filtered(
        self,
        query_params: EventValueQueryParams,
        property_filters: builtins.list[tuple[str, str]],
    ) -> response.Response:
        # TODO: this duplicates most of PropertyValuesQueryRunner._event_query. We should prob extend
        # PropertyValuesQuery with an optional property_filters field so the runner handles both paths
        # in the future.
        chain: list[str | int] = [query_params.key] if query_params.is_column else ["properties", query_params.key]
        date_from = relative_date_parse("-7d", query_params.team.timezone_info).strftime("%Y-%m-%d 00:00:00")
        date_to = timezone.now().astimezone(query_params.team.timezone_info).strftime("%Y-%m-%d 23:59:59")

        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_from),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=date_to),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=chain),
                right=ast.Constant(value=None),
            ),
        ]

        for param_key, param_value in property_filters:
            filter_key = param_key.replace("properties_", "", 1)
            try:
                filter_values = json.loads(param_value)
                conditions.append(create_property_conditions(filter_key, filter_values))
            except json.JSONDecodeError:
                conditions.append(create_property_conditions(filter_key, param_value))

        if query_params.event_names:
            event_conditions: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=name),
                )
                for name in query_params.event_names
            ]
            conditions.append(ast.Or(exprs=event_conditions) if len(event_conditions) > 1 else event_conditions[0])

        if query_params.value:
            escaped = query_params.value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.ILike,
                    left=ast.Call(name="toString", args=[ast.Field(chain=chain)]),
                    right=ast.Constant(value=f"%{escaped}%"),
                )
            )

        order_by: list[ast.OrderExpr] = (
            [
                ast.OrderExpr(
                    expr=ast.Call(name="length", args=[ast.Call(name="toString", args=[ast.Field(chain=chain)])]),
                    order="ASC",
                )
            ]
            if query_params.value
            else []
        )

        query = ast.SelectQuery(
            select=[ast.Field(chain=chain)],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            order_by=order_by,
            limit=ast.Constant(value=10),
        )

        result = execute_hogql_query(query, team=query_params.team)

        values = []
        for row in result.results:
            if isinstance(row[0], float | int | bool | uuid.UUID):
                values.append(row[0])
            else:
                try:
                    values.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    values.append(row[0])

        return self._return_with_short_cache(
            [{"name": convert_property_value(v)} for v in flatten(values)], refreshing=False
        )

    @staticmethod
    def _return_with_short_cache(values: builtins.list, refreshing: bool = False) -> response.Response:
        resp = response.Response({"results": values, "refreshing": refreshing})
        resp["Cache-Control"] = "max-age=10"
        return resp

    def _parse_properties_param(self, request: request.Request) -> "builtins.list[dict] | dict | None":
        """Parse the `properties` query param for `EventsQuery`.

        A flat list of leaf filters maps to `EventsQuery.properties`; a property group
        (`{"type": "AND"/"OR", "values": [...]}`, possibly nested) is returned intact and later
        forwarded to the runner's `property_to_expr` via `fixedProperties`, so its AND/OR survives.
        Legacy-only keys (`property_type`, `property_type_format`) the schema rejects are dropped;
        missing `type` defaults to `event` as before. Invalid JSON raises the legacy 400."""
        raw = request.GET.get("properties")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Properties are unparsable!")
        if isinstance(parsed, dict) and isinstance(parsed.get("values"), list):
            return _clean_property_node(parsed)
        if isinstance(parsed, list):
            return [_clean_property_node(prop) for prop in parsed if isinstance(prop, dict)]
        return None

    def _reject_restricted_property_references(
        self,
        properties: "builtins.list[dict] | dict | None",
        order_by: builtins.list[str],
        restricted_context: dict,
    ) -> None:
        """
        Raise a 400 if the request references a property the user can't read.
        """
        restricted_event = restricted_context.get("restricted_event_properties") or set()
        restricted_person = restricted_context.get("restricted_person_properties") or set()
        if not restricted_event and not restricted_person:
            return

        for prop in _iter_leaf_property_filters(properties):
            prop_type = prop.get("type", "event")
            key = prop.get("key")
            if prop_type == "event" and key in restricted_event:
                raise serializers.ValidationError("Filter references a restricted property")
            if prop_type == "person" and key in restricted_person:
                raise serializers.ValidationError("Filter references a restricted property")

        for entry in order_by:
            if not isinstance(entry, str):
                continue  # type: ignore
            field = entry.lstrip("-")
            # Accept both `properties.foo` (event) and `person.properties.foo` / `person_properties.foo`.
            if field.startswith("properties."):
                key = field.split(".", 1)[1]
                if key in restricted_event:
                    raise serializers.ValidationError("Order by references a restricted property")
            elif field.startswith("person.properties.") or field.startswith("person_properties."):
                key = field.split(".", 1)[1].split(".", 1)[-1]
                if key in restricted_person:
                    raise serializers.ValidationError("Order by references a restricted property")

    def _get_restricted_properties_context(self, request: request.Request, team: Team) -> dict:
        """Returns serializer context entries for field-level access control."""
        from products.access_control.backend.property_access_control import get_restricted_properties_for_team

        user = request.user if request.user.is_authenticated else None

        restricted = get_restricted_properties_for_team(team_id=team.pk, user=cast(User | None, user), team=team)
        restricted_event_properties = {name for name, ptype in restricted if ptype == PropertyDefinition.Type.EVENT}
        restricted_person_properties = {name for name, ptype in restricted if ptype == PropertyDefinition.Type.PERSON}

        return {
            "restricted_event_properties": restricted_event_properties,
            "restricted_person_properties": restricted_person_properties,
        }

    @tracer.start_as_current_span("events_api_is_property_hidden")
    def _is_property_hidden(self, key: str, team: Team) -> bool:
        property_is_hidden = False
        try:
            from ee.models.property_definition import EnterprisePropertyDefinition

            property_is_hidden = EnterprisePropertyDefinition.objects.filter(
                team=team,
                name=key,
                type=PropertyDefinition.Type.EVENT.value,
                hidden=True,
            ).exists()
        except ImportError:
            # Enterprise features not available, continue normally
            pass

        return property_is_hidden

    def _is_property_restricted(self, key: str, team: Team) -> bool:
        """Checks if a property key is restricted for the current user."""
        from products.access_control.backend.property_access_control import get_restricted_property_names

        user = self.request.user if self.request.user.is_authenticated else None
        restricted = get_restricted_property_names(
            team_id=team.pk,
            user=user,
            property_type=PropertyDefinition.Type.EVENT,
        )
        return key in restricted

    @tracer.start_as_current_span("events_api_custom_event_values")
    def _custom_event_values(self, query_params: EventValueQueryParams) -> response.Response:
        system_events = [
            event_name
            for event_name in CORE_FILTER_DEFINITIONS_BY_GROUP["events"].keys()
            if event_name != "All Events"  # Skip the wildcard
        ]
        query = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.NotIn,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=system_events),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["event"]), order="ASC")],
        )

        result = execute_hogql_query(query, team=query_params.team)

        return self._return_with_short_cache([{"name": event[0]} for event in result.results], refreshing=False)


class LegacyEventViewSet(EventViewSet):
    param_derived_from_user_current_team = "team_id"
