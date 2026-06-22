import json
import time
import uuid
import random
import urllib
import builtins
import dataclasses
from datetime import datetime, timedelta
from typing import Any, Iterator, List, Optional, Union, cast  # noqa: UP035
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from dateutil.parser import isoparse
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

from posthog.schema import EventsQuery, HogQLQueryModifiers, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.property_utils import create_property_conditions
from posthog.hogql.query import execute_hogql_query

from posthog.api.documentation import PropertiesSerializer, extend_schema
from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import get_events_list_rate_limiter
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.event_usage import get_request_analytics_properties
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Element, Person, PropertyDefinition, User
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    EventValuesBurstThrottle,
    EventValuesSustainedThrottle,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.utils import (
    convert_property_value,
    flatten,
    generate_short_id,
    refresh_requested_by_client,
    relative_date_parse,
)

from products.actions.backend.models.action import Action

tracer = trace.get_tracer(__name__)

EVENT_VALUES_COUNTER = Counter(
    "posthog_event_values_request",
    "Requests to the events/values endpoint",
    labelnames=["has_event_name", "auth"],
)

QUERY_DEFAULT_EXPORT_LIMIT = 1_000
EVENT_LIST_MAX_LIMIT = 1_000

# Progressive time windows in seconds: 1min, 5min, 15min, 1hr, 6hr, 24hr
EVENT_LIST_TIME_WINDOWS = [60, 300, 900, 3600, 21600, 86400]
EVENT_LIST_CACHE_TTL = 86400  # 24 hours
EVENT_LIST_CACHE_KEY_PREFIX = "event_list_good_period"


def _get_limit_size_category(limit: int) -> str:
    """Groups limits into size categories to limit cache key cardinality."""
    if limit < 1000:
        return "s"
    elif limit < 10000:
        return "m"
    return "l"


def _get_event_list_cache_key(
    team_id: int,
    has_event_filter: bool,
    has_distinct_id: bool,
    limit: int,
) -> str:
    """
    Generate a cache key for the event list progressive window optimization.

    The cache stores {"window": int, "result_count": int} to track which time
    window worked and how many results it returned. When reading from cache,
    we only use the cached window if its result_count >= half_limit for the
    current request. This prevents the bug where a cached window that succeeded
    for a smaller limit (e.g., 4999 with half_limit=2499) is incorrectly used
    for a larger limit (e.g., 6000 with half_limit=3000) that needs more results.

    We use size categories (s/m/l) instead of exact limits to bound cache key
    cardinality to ~3 keys per team/filter combination. Within a size category,
    different limits share the same cache key but have different half_limit
    thresholds - the result_count validation handles this.
    """
    event_flag = "1" if has_event_filter else "0"
    distinct_id_flag = "1" if has_distinct_id else "0"
    size_category = _get_limit_size_category(limit)
    return f"{EVENT_LIST_CACHE_KEY_PREFIX}:{team_id}:{event_flag}:{distinct_id_flag}:{size_category}"


# Columns the events list/retrieve endpoints read. The order is the contract for
# zipping HogQL result rows back into the dict shape `ClickhouseEventSerializer` expects.
EVENT_LIST_SELECT_COLUMNS = ["uuid", "event", "properties", "timestamp", "distinct_id", "elements_chain"]


def parse_timestamp(timestamp: str, tzinfo: ZoneInfo) -> datetime:
    try:
        parsed = isoparse(timestamp)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tzinfo)
        return parsed
    except ValueError:
        return relative_date_parse(timestamp, tzinfo)


def run_events_query(
    *,
    team: Team,
    user: Optional[User],
    database: Database,
    modifiers: HogQLQueryModifiers,
    limit: int,
    offset: int,
    order: str,
    before: Optional[str],
    after: Optional[str],
    event: Optional[str],
    person_id: Optional[str],
    distinct_id: Optional[str],
    properties: Optional[builtins.list[dict]],
    action_id: Optional[str],
    time_window_seconds: Optional[int] = None,
) -> tuple[builtins.list[dict], bool, Optional[int]]:
    """Run a single events-list page through HogQL's `EventsQueryRunner`.

    Returns the page rows (already trimmed to `limit`), whether more rows exist, and the
    time window that was applied (`None` when the request's own date range was used). The
    progressive-window probing and result-count cache live in `list()`; this is one probe.
    Heavy event-list scans run on the OFFLINE workload, isolated from the main query nodes.
    The `database`/`modifiers` are built once per request and shared across probes so the
    HogQL schema isn't rebuilt on every window.
    """
    tzinfo = team.timezone_info

    before_dt = parse_timestamp(before, tzinfo) if before else datetime.now(tzinfo) + timedelta(seconds=5)
    if after:
        after_dt: Optional[datetime] = parse_timestamp(after, tzinfo)
    elif settings.PATCH_EVENT_LIST_MAX_OFFSET > 1:
        after_dt = before_dt - timedelta(hours=24)
    else:
        after_dt = None

    if settings.PATCH_EVENT_LIST_MAX_OFFSET > 0 and after_dt is not None:
        if (before_dt - after_dt) > timedelta(days=366) and (
            settings.PATCH_EVENT_LIST_MAX_OFFSET > 1 or random.random() < 0.01
        ):
            raise ValueError("Date range cannot exceed 1 year")

    applied_window_seconds: Optional[int] = None
    if (
        order == "DESC"
        and time_window_seconds is not None
        and (after_dt is None or (before_dt - after_dt).total_seconds() > time_window_seconds)
    ):
        after_dt = before_dt - timedelta(seconds=time_window_seconds)
        applied_window_seconds = time_window_seconds

    # Match the legacy behaviour for actions with no match groups (or that no longer exist):
    # an empty result, not an error. The runner would otherwise raise.
    if action_id:
        try:
            action = Action.objects.get(pk=int(action_id), team__project_id=team.project_id)
        except (Action.DoesNotExist, ValueError):
            return [], False, applied_window_seconds
        if not action.steps:
            return [], False, applied_window_seconds

    where_properties: builtins.list[dict] = list(properties) if properties else []
    if distinct_id is not None:
        where_properties.append(
            {"type": "event_metadata", "key": "distinct_id", "value": distinct_id, "operator": "exact"}
        )

    events_query = EventsQuery(
        select=EVENT_LIST_SELECT_COLUMNS,
        before=before_dt.isoformat(),
        # "all" disables the runner's lower timestamp bound — matches the legacy path, which
        # applied no `timestamp >` condition when there was no `after` and no window.
        after=after_dt.isoformat() if after_dt is not None else "all",
        event=event or None,
        personId=str(person_id) if person_id else None,
        actionId=int(action_id) if action_id else None,
        properties=cast("builtins.list[dict[str, object]]", where_properties) if where_properties else None,
        orderBy=[f"timestamp {order}"],
        limit=limit,
        offset=offset,
    )

    runner = EventsQueryRunner(query=events_query, team=team, user=user, modifiers=modifiers)
    rows, has_more = _execute_events_list_query(runner, database)
    return rows, has_more, applied_window_seconds


def _execute_events_list_query(runner: EventsQueryRunner, database: Database) -> tuple[builtins.list[dict], bool]:
    """Execute the events-list HogQL query and return ``(page_rows, has_more)``.

    Split out from `run_events_query` so the progressive-window probing in `list()` can be
    tested against the real window/date logic while stubbing only the ClickHouse round-trip.
    The pre-built `database` is handed to the executor so it isn't rebuilt for each probe.
    """
    runner.paginator.execute_hogql_query(
        runner.to_query(),
        query_type="events_list",
        team=runner.team,
        workload=Workload.OFFLINE,
        settings=HogQLGlobalSettings(max_threads=settings.CLICKHOUSE_EVENT_LIST_MAX_THREADS),
        modifiers=runner.modifiers,
        timings=runner.timings,
        user=runner.user,
        context=HogQLContext(team=runner.team, database=database, enable_select_queries=True),
    )
    rows = [dict(zip(EVENT_LIST_SELECT_COLUMNS, row)) for row in runner.paginator.results]
    return rows, runner.paginator.has_more()


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

            # Progressive time window optimization
            # Start with cached good_period or smallest window
            has_event_filter = bool(request.GET.get("event"))
            has_distinct_id = bool(request.GET.get("distinct_id"))
            cache_key = _get_event_list_cache_key(team.pk, has_event_filter, has_distinct_id, limit)
            cached_data = cache.get(cache_key)

            # Calculate the user's requested time range in seconds
            request_window_seconds: Optional[int] = None
            if request.GET.get("before") and request.GET.get("after"):
                try:
                    before_dt = relative_date_parse(request.GET["before"], team.timezone_info)
                    after_dt = relative_date_parse(request.GET["after"], team.timezone_info)
                    request_window_seconds = int((before_dt - after_dt).total_seconds())
                except (ValueError, TypeError):
                    pass

            # Build list of windows to try, only those shorter than request window
            windows_to_try = [
                w for w in EVENT_LIST_TIME_WINDOWS if request_window_seconds is None or w < request_window_seconds
            ]

            half_limit = max(limit // 2, 1)  # At least 1 result required

            # Only use cached window if it returned enough results for our threshold.
            # This prevents the bug where a cached window that succeeded for a smaller
            # limit (e.g., 4999 with half_limit=2499) is used for a larger limit
            # (e.g., 6000 with half_limit=3000) that needs more results.
            cached_window = None
            if cached_data and isinstance(cached_data, dict):
                cached_result_count = cached_data.get("result_count", 0)
                if cached_result_count >= half_limit:
                    cached_window = cached_data.get("window")
            elif cached_data and isinstance(cached_data, int):
                # Backwards compatibility: old cache format was just the window integer
                cached_window = cached_data

            if cached_window and cached_window in windows_to_try:
                windows_to_try.remove(cached_window)
                windows_to_try.insert(0, cached_window)

            task_id = generate_short_id()

            # Build the HogQL schema once and share it across every window probe — otherwise the
            # progressive-window loop would rebuild the (data-warehouse-aware) database per probe.
            request_user = cast(Optional[User], request.user if request.user.is_authenticated else None)
            shared_modifiers = create_default_modifiers_for_team(team)
            shared_database = Database.create_for(team=team, user=request_user, modifiers=shared_modifiers)

            runner_kwargs: dict[str, Any] = {
                "team": team,
                "user": request_user,
                "database": shared_database,
                "modifiers": shared_modifiers,
                "limit": limit,
                "offset": offset,
                "order": order,
                "before": request.GET.get("before"),
                "after": request.GET.get("after"),
                "event": request.GET.get("event"),
                "person_id": request.GET.get("person_id"),
                "distinct_id": request.GET.get("distinct_id"),
                "properties": properties,
                "action_id": request.GET.get("action_id"),
            }

            with get_events_list_rate_limiter().run(team_id=team.pk, task_id=task_id):
                query_result: list = []
                has_more = False
                successful_window: Optional[int] = None
                applied_window: Optional[int] = None

                for window in windows_to_try:
                    query_result, has_more, applied_window = run_events_query(
                        **runner_kwargs, time_window_seconds=window
                    )

                    # If window wasn't applied (e.g., ASC order), don't try other windows
                    if applied_window is None:
                        break

                    if len(query_result) >= half_limit:
                        successful_window = window
                        break

                if successful_window:
                    # Cache the successful window AND result count for future requests.
                    # This allows requests with smaller limits to reuse cached windows,
                    # while requests with larger limits will find their own windows.
                    # Cache format: {"window": int, "result_count": int} (or int for legacy)
                    new_cache_data = {"window": successful_window, "result_count": len(query_result)}
                    if new_cache_data != cached_data:
                        cache.set(cache_key, new_cache_data, EVENT_LIST_CACHE_TTL)
                elif applied_window is not None or not windows_to_try:
                    # Windows were applied but didn't return enough results, or no windows to try - run full query
                    query_result, has_more, applied_window = run_events_query(**runner_kwargs)

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
        query = ast.SelectQuery(
            select=[ast.Field(chain=[column]) for column in EVENT_LIST_SELECT_COLUMNS],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["uuid"]),
                right=ast.Constant(value=uuid.UUID(pk)),
            ),
        )
        result = execute_hogql_query(query, team=self.team, query_type="event_detail")
        if not result.results:
            raise NotFound(detail=f"No events exist for event UUID {pk}")

        query_result = [dict(zip(EVENT_LIST_SELECT_COLUMNS, result.results[0]))]
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

    def _parse_properties_param(self, request: request.Request) -> Optional[builtins.list[dict]]:
        """Parse the `properties` query param into a flat list of property-filter dicts for
        `EventsQuery.properties`. Legacy-only keys (`property_type`, `property_type_format`)
        that the schema rejects are dropped; missing `type` defaults to `event` as before."""
        raw = request.GET.get("properties")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Properties are unparsable!")
        # A property group ({"type": "AND", "values": [...]}) collapses to its values.
        if isinstance(parsed, dict) and "values" in parsed:
            parsed = parsed.get("values") or []
        if not isinstance(parsed, list):
            return None
        allowed = {"key", "value", "operator", "type", "label", "group_type_index"}
        return [{k: v for k, v in prop.items() if k in allowed} for prop in parsed if isinstance(prop, dict)]

    def _reject_restricted_property_references(
        self,
        properties: Optional[builtins.list[dict]],
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

        for prop in properties or []:
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

        restricted = get_restricted_properties_for_team(team_id=team.pk, user=cast(User | None, user))
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
