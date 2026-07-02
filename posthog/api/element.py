from typing import Literal

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, extend_schema
from opentelemetry import trace
from prometheus_client import Histogram
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import ProductKey

from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered, action
from posthog.clickhouse.client import sync_execute
from posthog.models import Element, Filter
from posthog.models.element.element import build_attributes_filter, chain_to_element_dicts
from posthog.models.element.sql import GET_ELEMENTS, GET_VALUES
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.query_date_range import QueryDateRange
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
                filter = Filter(request=request, team=self.team)
                date_params = {}
                query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=True)
                date_from, date_from_params = query_date_range.date_from
                date_to, date_to_params = query_date_range.date_to
                date_params.update(date_from_params)
                date_params.update(date_to_params)

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

                # unless someone is using this as an API client, this is only for the toolbar,
                # which only ever queries date range, event type, and URL
                prop_filters, prop_filter_params = parse_prop_grouped_clauses(
                    team_id=self.team.pk,
                    property_group=filter.property_groups,
                    hogql_context=filter.hogql_context,
                )

            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("limit", limit)
            span.set_attribute("offset", offset)
            span.set_attribute("sampling_factor", sampling_factor)
            span.set_attribute("include_event_types", ",".join(sorted(events_filter)))

            with timer("execute_query"), tracer.start_as_current_span("elements_api_stats.execute_query"):
                result = sync_execute(
                    GET_ELEMENTS.format(
                        date_from=date_from,
                        date_to=date_to,
                        query=prop_filters,
                        sampling_factor=sampling_factor,
                        limit=limit + 1,
                        offset=offset,
                    ),
                    {
                        "team_id": self.team.pk,
                        "timezone": self.team.timezone,
                        "sampling_factor": sampling_factor,
                        **prop_filter_params,
                        **date_params,
                        "filter_event_types": events_filter,
                        **filter.hogql_context.values,
                    },
                )

            with timer("serialize_elements"), tracer.start_as_current_span("elements_api_stats.serialize_elements"):
                # parses chains straight to response dicts (shaped exactly like
                # ElementStatsSerializer output, which stays as the declared schema)
                serialized_elements = [
                    {
                        "count": int(row[1]),
                        "hash": f"{row[3]:x}",
                        "type": row[2],
                        "elements": chain_to_element_dicts(row[0], attributes_filter),
                    }
                    for row in result[:limit]
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
