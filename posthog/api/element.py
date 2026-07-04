from datetime import datetime
from typing import Literal

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from opentelemetry import trace
from prometheus_client import Histogram
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import DateRange, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered, action
from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Element, Filter
from posthog.models.element.element import build_attributes_filter, chain_to_element_dicts
from posthog.models.element.sql import GET_VALUES
from posthog.utils import format_query_params_absolute_url

tracer = trace.get_tracer(__name__)

ELEMENT_STATS_TIME_HISTOGRAM = Histogram(
    "element_stats_time_seconds",
    "How long does it take to get element stats?",
)

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
                description="Event types to include: $autocapture, $rageclick, $dead_click. Defaults to all three.",
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
                "date_from",
                type=str,
                description="Start of the date range (e.g. -7d, 2024-01-01). Defaults to last 7 days.",
            ),
            OpenApiParameter(
                "date_to",
                type=str,
                description="End of the date range (e.g. 2024-01-31). Defaults to now.",
            ),
        ],
        responses=ElementStatsResponseSerializer,
    )
    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        """
        The original version of this API always and only returned $autocapture elements
        If no include query parameter is sent this remains true.
        Now, you can pass a combination of include query parameters to get different types of elements
        Currently only $autocapture and $rageclick and $dead_click are supported
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

                try:
                    limit = int(request.query_params.get("limit", settings.ELEMENT_STATS_DEFAULT_LIMIT))
                except ValueError:
                    raise ValidationError("Limit must be an integer")

                try:
                    offset = int(request.query_params.get("offset", 0))
                except ValueError:
                    raise ValidationError("offset must be an integer")

                try:
                    sampling_factor = float(request.query_params.get("sampling_factor", 1))
                except ValueError:
                    raise ValidationError("sampling_factor must be a float")

                events_filter = self._events_filter(request)

                attributes_filter = build_attributes_filter(request.query_params.get("data_attributes", "").split(","))

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
                        "date_from": ast.Constant(value=date_range.date_from()),
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
                        "elements": chain_to_element_dicts(chain, attributes_filter),
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
        events_to_include = set(request.query_params.getlist("include", []))

        if not events_to_include:
            return tuple(supported_events)

        if not events_to_include.issubset(supported_events):
            raise ValidationError("Only $autocapture, $rageclick, and $dead_click are supported.")

        return tuple(events_to_include)

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="element").time(),
            tracer.start_as_current_span("elements_api_property_values") as span,
        ):
            key = request.GET.get("key")
            value = request.GET.get("value")

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("property_key", key or "")
            span.set_attribute("has_value_filter", value is not None)

            select_regex = '[:|"]{}="(.*?)"'.format(key)

            # Make sure key exists, otherwise could lead to sql injection lower down
            if key not in self.serializer_class.Meta.fields:
                return response.Response([])

            if key == "tag_name":
                select_regex = r"^([-_a-zA-Z0-9]*?)[\.|:]"
                filter_regex = select_regex
                if value:
                    filter_regex = r"^([-_a-zA-Z0-9]*?{}[-_a-zA-Z0-9]*?)[\.|:]".format(value)
            else:
                if value:
                    filter_regex = '[:|"]{}=".*?{}.*?"'.format(key, value)
                else:
                    filter_regex = select_regex

            result = sync_execute(
                GET_VALUES.format(),
                {
                    "team_id": self.team.id,
                    "regex": select_regex,
                    "filter_regex": filter_regex,
                },
            )
            span.set_attribute("result_count", len(result))
            return response.Response([{"name": value[0]} for value in result])


class LegacyElementViewSet(ElementViewSet):
    param_derived_from_user_current_team = "team_id"
