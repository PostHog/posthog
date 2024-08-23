from typing import Literal

from rest_framework import request, response, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from statshog.defaults.django import statsd

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.client import sync_execute
from posthog.models import Element, Filter
from posthog.models.element.element import chain_to_elements
from posthog.models.element.sql import GET_ELEMENTS, GET_VALUES
from posthog.models.instance_setting import get_instance_setting
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.query_date_range import QueryDateRange
from posthog.utils import format_query_params_absolute_url


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
        Currently only $autocapture and $rageclick are supported
        """

        sample_rows_count = get_instance_setting("HEATMAP_SAMPLE_N") or 2_000_000

        filter = Filter(request=request, team=self.team)

        date_params = {}
        query_date_range = QueryDateRange(filter=filter, team=self.team, should_round=True)
        date_from, date_from_params = query_date_range.date_from
        date_to, date_to_params = query_date_range.date_to
        date_params.update(date_from_params)
        date_params.update(date_to_params)

        try:
            limit = int(request.query_params.get("limit", 250))
        except ValueError:
            raise ValidationError("Limit must be an integer")

        try:
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            raise ValidationError("offset must be an integer")

        events_filter = self._events_filter(request)

        paginate_response = request.query_params.get("paginate_response", "false") == "true"
        if not paginate_response:
            # once we are getting no hits on this counter we can default to paginated responses
            statsd.incr(
                "toolbar_element_stats_unpaginated_api_request_tombstone",
                tags={"team_id": self.team_id},
            )

        prop_filters, prop_filter_params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )
        result = sync_execute(
            GET_ELEMENTS.format(
                date_from=date_from,
                date_to=date_to,
                query=prop_filters,
                limit=limit + 1,
                offset=offset,
            ),
            {
                "team_id": self.team.pk,
                "timezone": self.team.timezone,
                "sample_rows_count": sample_rows_count,
                **prop_filter_params,
                **date_params,
                "filter_event_types": events_filter,
                **filter.hogql_context.values,
            },
        )
        serialized_elements = [
            {
                "count": elements[1],
                "hash": None,
                "type": elements[2],
                "elements": [ElementSerializer(element).data for element in chain_to_elements(elements[0])],
            }
            for elements in result[:limit]
        ]

        if paginate_response:
            has_next = len(result) == limit + 1
            next_url = format_query_params_absolute_url(request, offset + limit) if has_next else None
            previous_url = format_query_params_absolute_url(request, offset - limit) if offset - limit >= 0 else None
            return response.Response(
                {
                    "results": serialized_elements,
                    "next": next_url,
                    "previous": previous_url,
                }
            )
        else:
            return response.Response(serialized_elements)

    def _events_filter(self, request) -> tuple[Literal["$autocapture", "$rageclick"], ...]:
        event_to_filter: tuple[Literal["$autocapture", "$rageclick"], ...] = ()
        # when multiple includes are sent expects them as separate parameters
        # e.g. ?include=a&include=b
        events_to_include = request.query_params.getlist("include", [])

        if not events_to_include:
            # sensible default when not provided
            event_to_filter += ("$autocapture",)
            event_to_filter += ("$rageclick",)
        else:
            if "$rageclick" in events_to_include:
                events_to_include.remove("$rageclick")
                event_to_filter += ("$rageclick",)

            if "$autocapture" in events_to_include:
                events_to_include.remove("$autocapture")
                event_to_filter += ("$autocapture",)

            if events_to_include:
                raise ValidationError("Only $autocapture and $rageclick are supported for now.")
        return event_to_filter

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
