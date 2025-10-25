from typing import Literal

from prometheus_client import Histogram
from rest_framework import request, response, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import ServerTimingsGathered, action
from posthog.auth import TemporaryTokenAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.models import Element, Filter
from posthog.models.element.element import chain_to_elements
from posthog.models.element.sql import GET_ELEMENTS, GET_VALUES
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.query_date_range import QueryDateRange
from posthog.utils import format_query_params_absolute_url

ELEMENT_STATS_TIME_HISTOGRAM = Histogram(
    "element_stats_time_seconds",
    "How long does it take to get element stats?",
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
    count = serializers.IntegerField()
    hash = serializers.CharField(allow_null=True)
    type = serializers.CharField()
    elements = ElementSerializer(many=True)


class ElementViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    filter_rewrite_rules = {"team_id": "group__team_id"}

    queryset = Element.objects.all()
    serializer_class = ElementSerializer
    authentication_classes = [TemporaryTokenAuthentication]

    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        """
        The original version of this API always and only returned $autocapture elements
        If no include query parameter is sent this remains true.
        Now, you can pass a combination of include query parameters to get different types of elements
        Currently only $autocapture and $rageclick and $dead_click are supported
        """

        with ELEMENT_STATS_TIME_HISTOGRAM.time():
            timer = ServerTimingsGathered()

            with timer("prepare_for_query"):
                filter = Filter(request=request, team=self.team)
                date_params = {}
                query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=True)
                date_from, date_from_params = query_date_range.date_from
                date_to, date_to_params = query_date_range.date_to
                date_params.update(date_from_params)
                date_params.update(date_to_params)

                try:
                    limit = int(request.query_params.get("limit", 10_000))
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

                # unless someone is using this as an API client, this is only for the toolbar,
                # which only ever queries date range, event type, and URL
                prop_filters, prop_filter_params = parse_prop_grouped_clauses(
                    team_id=self.team.pk,
                    property_group=filter.property_groups,
                    hogql_context=filter.hogql_context,
                )

            with timer("execute_query"):
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

            with timer("prepare_for_serialization"):
                elements_data = [
                    {
                        "count": elements[1],
                        "hash": None,
                        "type": elements[2],
                        "elements": chain_to_elements(elements[0]),
                    }
                    for elements in result[:limit]
                ]

            with timer("serialize_elements"):
                serialized_elements = ElementStatsSerializer(elements_data, many=True).data

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
        key = request.GET.get("key")
        value = request.GET.get("value")
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
        return response.Response([{"name": value[0]} for value in result])


class LegacyElementViewSet(ElementViewSet):
    param_derived_from_user_current_team = "team_id"
