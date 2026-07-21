import re
import json
from datetime import datetime
from typing import Literal, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from opentelemetry import trace
from prometheus_client import Histogram
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import DateRange, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_HEATMAPS_LIMIT, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered, action
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Element, Filter
from posthog.models.element.element import build_attributes_filter, chain_to_element_dicts
from posthog.utils import format_query_params_absolute_url

tracer = trace.get_tracer(__name__)

ELEMENT_STATS_TIME_HISTOGRAM = Histogram(
    "element_stats_time_seconds",
    "How long does it take to get element stats?",
)

# element properties that appear as string values in elements_chain and can be
# matched by the values regexes below; attr_class is excluded because classes are
# serialized as .classname tokens in the tag part of the chain, not as
# attr_class="..." key-value pairs, so the generic regex cannot match them
SUPPORTED_VALUES_KEYS = {"tag_name", "text", "href", "attr_id"}
_SUPPORTED_VALUES_KEYS_DISPLAY = ", ".join(sorted(SUPPORTED_VALUES_KEYS))
KEYS_WITH_NO_LISTABLE_VALUES = {"selector"}

ELEMENT_STATS_RESULT_COUNT_HISTOGRAM = Histogram(
    "element_stats_result_count",
    "Number of results returned by element stats endpoint",
    labelnames=["limit"],
    buckets=[100, 500, 1000, 5000, 10000, 25000, 50000, 100000],
)


class ElementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Element
        fields = [
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


class ElementStatsSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of events matching this element chain")
    hash = serializers.CharField(
        allow_null=True,
        help_text="Stable identity of the raw element chain (hash computed before any attribute filtering), for deduplicating rows across pages",
    )
    type = serializers.CharField(help_text="Event type: $autocapture, $rageclick, or $dead_click")
    elements = ElementSerializer(many=True, help_text="Parsed elements of the chain, clicked element first")


class ElementStatsResponseSerializer(serializers.Serializer):
    results = ElementStatsSerializer(many=True, help_text="Element chains with event counts, ordered by count")
    next = serializers.CharField(allow_null=True, help_text="URL for the next page of results, if any")
    previous = serializers.CharField(allow_null=True, help_text="URL for the previous page of results, if any")


class ElementValueSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="A distinct value of the requested element property")


@extend_schema(extensions={"x-product": ProductKey.PRODUCT_ANALYTICS})
class ElementViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "element"
    scope_object_read_actions = ["list", "retrieve", "stats", "values"]
    filter_rewrite_rules = {"team_id": "group__team_id"}

    queryset = Element.objects.all()
    serializer_class = ElementSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "include",
                type=str,
                many=True,
                description=(
                    "Event types to include: $autocapture, $rageclick, $dead_click. Defaults to all three. "
                    "Accepts repeated parameters, a JSON array, or a comma-separated list."
                ),
            ),
            OpenApiParameter("limit", type=int, description="Maximum rows per page"),
            OpenApiParameter("offset", type=int, description="Pagination offset"),
            OpenApiParameter("sampling_factor", type=float, description="Sampling factor between 0 and 1"),
            OpenApiParameter(
                "data_attributes",
                type=str,
                description=(
                    "Comma-separated data attribute names (wildcards allowed, e.g. data-*). When provided, "
                    "each element's attributes map is filtered to matching attr__* keys, shrinking the response."
                ),
            ),
            OpenApiParameter(
                "max_element_chain_depth",
                type=int,
                description=(
                    "Maximum number of elements returned per chain, keeping the clicked element (order 0) "
                    "and its nearest ancestors. Bounds the deep DOM ancestor chain up to <body> that inflates "
                    "responses. Defaults to unbounded (the full chain)."
                ),
            ),
            OpenApiParameter(
                "date_from",
                type=str,
                description="Start of the date range (e.g. -7d, 2024-01-01). Defaults to last 7 days.",
            ),
            OpenApiParameter(
                "date_to",
                type=str,
                description="End of the date range (e.g. 2024-01-31). Defaults to now.",
            ),
            OpenApiParameter(
                "properties",
                type=str,
                description=(
                    "JSON-encoded list of property filters to apply to the underlying events, e.g. "
                    '[{"key": "$current_url", "value": "https://example.com/page"}] or '
                    '[{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}]. '
                    "Supports event, person, cohort, element, and HogQL property filter types."
                ),
            ),
            OpenApiParameter(
                "filter_test_accounts",
                type=bool,
                description=(
                    "When true, applies the project's internal-and-test-account filters to the underlying events. "
                    "Pass the lowercase string true; other truthy spellings are ignored."
                ),
            ),
        ],
        responses=ElementStatsResponseSerializer,
    )
    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        """
        Counts of $autocapture, $rageclick, and $dead_click events grouped by the element chain
        they occurred on, ordered by count. Defaults to all three event types; narrow with the
        include parameter.
        """

        with (
            ELEMENT_STATS_TIME_HISTOGRAM.time(),
            tracer.start_as_current_span("elements_api_stats") as span,
        ):
            timer = ServerTimingsGathered()

            with timer("prepare_for_query"), tracer.start_as_current_span("elements_api_stats.prepare_for_query"):
                # Filter parses the properties param (including property groups) and folds the
                # team's test-account filters in when filter_test_accounts is set
                filter = Filter(request=request, team=self.team)
                date_range = QueryDateRange(
                    date_range=DateRange(
                        date_from=request.query_params.get("date_from", "-7d"),
                        date_to=request.query_params.get("date_to"),
                    ),
                    team=self.team,
                    interval=None,
                    now=datetime.now(),
                )
                # the stats UI only picks a day, never a time, so always query from
                # the start of the chosen day (QueryDateRange leaves an absolute
                # date_from untruncated, unlike the relative "-7d" default)
                query_date_from = date_range.date_from().replace(hour=0, minute=0, second=0, microsecond=0)

                try:
                    limit = int(request.query_params.get("limit", settings.ELEMENT_STATS_DEFAULT_LIMIT))
                except ValueError:
                    raise ValidationError("limit must be an integer")
                # keep the limit + 1 pagination probe below the printer's hard cap, so
                # has_next can still see the extra row instead of it being clamped away
                if not 0 < limit < MAX_SELECT_HEATMAPS_LIMIT:
                    raise ValidationError(f"limit must be between 1 and {MAX_SELECT_HEATMAPS_LIMIT - 1}")

                try:
                    offset = int(request.query_params.get("offset", 0))
                except ValueError:
                    raise ValidationError("offset must be an integer")
                if offset < 0:
                    raise ValidationError("offset must be zero or greater")

                try:
                    sampling_factor = float(request.query_params.get("sampling_factor", 1))
                except ValueError:
                    raise ValidationError("sampling_factor must be a float")
                # 0 would silently return no rows (SAMPLE 0); out-of-range values 500 in ClickHouse
                if not 0 < sampling_factor <= 1:
                    raise ValidationError("sampling_factor must be greater than 0 and at most 1")

                events_filter = self._events_filter(request)

                attributes_filter = build_attributes_filter(request.query_params.get("data_attributes", "").split(","))

                max_element_chain_depth_param = request.query_params.get("max_element_chain_depth")
                if max_element_chain_depth_param is None:
                    max_element_chain_depth = None
                else:
                    try:
                        max_element_chain_depth = int(max_element_chain_depth_param)
                    except ValueError:
                        raise ValidationError("max_element_chain_depth must be an integer")
                    if max_element_chain_depth < 1:
                        raise ValidationError("max_element_chain_depth must be greater than zero")

                # HogQL resolves property access per the team's modifiers (materialized
                # columns, person-on-events mode), so no per-mode handling is needed here
                select = parse_select(
                    """
                    SELECT
                        elements_chain,
                        count() / {sampling_factor} AS occurrences,
                        event AS event_type,
                        cityHash64(elements_chain) AS chain_hash
                    FROM events
                    WHERE event IN {event_types}
                        AND elements_chain != ''
                        AND timestamp >= {date_from}
                        AND timestamp <= {date_to}
                        AND {property_filters}
                    GROUP BY elements_chain, event
                    ORDER BY occurrences DESC
                    LIMIT {limit} OFFSET {offset}
                    """,
                    placeholders={
                        "sampling_factor": ast.Constant(value=sampling_factor),
                        "event_types": ast.Constant(value=list(events_filter)),
                        "date_from": ast.Constant(value=query_date_from),
                        "date_to": ast.Constant(value=date_range.date_to()),
                        "property_filters": property_to_expr(filter.property_groups, team=self.team),
                        "limit": ast.Constant(value=limit + 1),
                        "offset": ast.Constant(value=offset),
                    },
                )
                assert isinstance(select, ast.SelectQuery) and select.select_from is not None
                if sampling_factor != 1:
                    select.select_from.sample = ast.SampleExpr(
                        sample_value=ast.RatioExpr(left=ast.Constant(value=sampling_factor))
                    )

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("limit", limit)
            span.set_attribute("offset", offset)
            span.set_attribute("sampling_factor", sampling_factor)
            span.set_attribute("include_event_types", ",".join(sorted(events_filter)))

            with timer("execute_query"), tracer.start_as_current_span("elements_api_stats.execute_query"):
                result = execute_hogql_query(
                    query=select,
                    team=self.team,
                    query_type="elements_stats",
                    # the toolbar paginates in pages of up to 50k, so limit + 1 must
                    # survive above the default 50k query cap
                    limit_context=LimitContext.HEATMAPS,
                ).results

            with timer("serialize_elements"), tracer.start_as_current_span("elements_api_stats.serialize_elements"):
                # parses chains straight to response dicts (shaped exactly like
                # ElementStatsSerializer output, which stays as the declared schema)
                serialized_elements = [
                    {
                        "count": int(count),
                        "hash": f"{chain_hash:x}",
                        "type": event_type,
                        "elements": chain_to_element_dicts(chain, attributes_filter, max_element_chain_depth),
                    }
                    for chain, count, event_type, chain_hash in result[:limit]
                ]

            span.set_attribute("result_count", len(serialized_elements))
            ELEMENT_STATS_RESULT_COUNT_HISTOGRAM.labels(limit=limit).observe(len(serialized_elements))

            has_next = len(result) == limit + 1
            next_url = format_query_params_absolute_url(request, offset + limit) if has_next else None
            previous_url = format_query_params_absolute_url(request, offset - limit) if offset - limit >= 0 else None
            elements_response = response.Response(
                {
                    "results": serialized_elements,
                    "next": next_url,
                    "previous": previous_url,
                }
            )

            elements_response.headers["Server-Timing"] = timer.to_header_string()
            elements_response.headers["Cache-Control"] = "public, max-age=30"  # Cache for 30 seconds
            elements_response.headers["Vary"] = "Accept, Accept-Encoding, Query-String"
            return elements_response

    def _events_filter(self, request) -> tuple[Literal["$autocapture", "$rageclick", "$dead_click"], ...]:
        supported_events: set[Literal["$autocapture", "$rageclick", "$dead_click"]] = {
            "$autocapture",
            "$rageclick",
            "$dead_click",
        }
        # accept repeated params (the toolbar), a JSON array string (the MCP client
        # serializes arrays with JSON.stringify), or a comma-separated list
        # (agents hand-typing comma-separated lists, e.g. "$rageclick, $autocapture")
        events_to_include: set[str] = set()
        for raw in request.query_params.getlist("include", []):
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    raise ValidationError("include must be a valid JSON array when passed as one")
                if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                    raise ValidationError("include must be a JSON array of event names")
                events_to_include.update(parsed)
            else:
                events_to_include.update(part.strip() for part in raw.split(",") if part.strip())

        if not events_to_include:
            return tuple(supported_events)

        if not events_to_include.issubset(supported_events):
            raise ValidationError("Only $autocapture, $rageclick, and $dead_click are supported.")

        return tuple(cast(set[Literal["$autocapture", "$rageclick", "$dead_click"]], events_to_include))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "key",
                type=str,
                required=True,
                description="Element property to list values for: tag_name, text, href, or attr_id.",
            ),
            OpenApiParameter(
                "value",
                type=str,
                description="Optional substring to filter values by (case-sensitive contains match).",
            ),
        ],
        responses=ElementValueSerializer(many=True),
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="element").time(),
            tracer.start_as_current_span("elements_api_property_values") as span,
        ):
            key = request.GET.get("key")
            value = request.GET.get("value")

            # the taxonomic filter offers selector and eagerly fetches its values,
            # but selectors are computed, not stored in elements_chain
            if key in KEYS_WITH_NO_LISTABLE_VALUES:
                return response.Response([])

            if key not in SUPPORTED_VALUES_KEYS:
                raise ValidationError(f"key must be one of {_SUPPORTED_VALUES_KEYS_DISPLAY}")

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("property_key", key)
            span.set_attribute("has_value_filter", value is not None)

            # the value is a user-typed substring, so escape it before it lands in a regex
            escaped_value = re.escape(value) if value else None

            if key == "tag_name":
                select_regex = r"^([-_a-zA-Z0-9]*?)[\.|:]"
                filter_regex = (
                    r"^([-_a-zA-Z0-9]*?{}[-_a-zA-Z0-9]*?)[\.|:]".format(escaped_value)
                    if escaped_value
                    else select_regex
                )
            else:
                select_regex = '[:|"]{}="(.*?)"'.format(key)
                filter_regex = '[:|"]{}=".*?{}.*?"'.format(key, escaped_value) if escaped_value else select_regex

            # no explicit team filter: execute_hogql_query scopes the events table to self.team
            select = parse_select(
                """
                SELECT extract(elements_chain, {select_regex}) AS value, count() AS occurrences
                FROM (
                    SELECT elements_chain
                    FROM events
                    WHERE event = '$autocapture'
                        AND elements_chain != ''
                        AND match(elements_chain, {filter_regex})
                    LIMIT 100000
                )
                GROUP BY value
                ORDER BY occurrences DESC
                LIMIT 100
                """,
                placeholders={
                    "select_regex": ast.Constant(value=select_regex),
                    "filter_regex": ast.Constant(value=filter_regex),
                },
            )
            result = execute_hogql_query(query=select, team=self.team, query_type="elements_values").results
            span.set_attribute("result_count", len(result))
            return response.Response([{"name": row[0]} for row in result])


class LegacyElementViewSet(ElementViewSet):
    param_derived_from_user_current_team = "team_id"
