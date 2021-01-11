from rest_framework import authentication, request, response, serializers, viewsets
from rest_framework.decorators import action

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.element import chain_to_elements
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.element import GET_ELEMENTS, GET_VALUES
from posthog.api.element import ElementSerializer, ElementViewSet
from posthog.models.filters import Filter


class ClickhouseElementViewSet(ElementViewSet):
    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        filter = Filter(request=request)

        date_from, date_to, _ = parse_timestamps(filter, team_id=self.team.pk)

        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, self.team.pk)
        result = sync_execute(
            GET_ELEMENTS.format(date_from=date_from, date_to=date_to, query=prop_filters),
            {"team_id": self.team.pk, **prop_filter_params},
        )
        return response.Response(
            [
                {
                    "count": elements[1],
                    "hash": None,
                    "elements": [ElementSerializer(element).data for element in chain_to_elements(elements[0])],
                }
                for elements in result
            ]
        )

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        key = request.GET.get("key")
        value = request.GET.get("value")
        select_regex = '[:|"]{}="(.*?)"'.format(key)

        # Make sure key exists, otherwise could lead to sql injection lower down
        if key not in self.serializer_class.Meta.fields:
            return response.Response([])

        if key == "tag_name":
            select_regex = "^([-_a-zA-Z0-9]*?)[\.|:]"
            filter_regex = select_regex
            if value:
                filter_regex = "^([-_a-zA-Z0-9]*?{}[-_a-zA-Z0-9]*?)[\.|:]".format(value)
        else:
            if value:
                filter_regex = '[:|"]{}=".*?{}.*?"'.format(key, value)
            else:
                filter_regex = select_regex

        result = sync_execute(
            GET_VALUES.format(), {"team_id": self.team.id, "regex": select_regex, "filter_regex": filter_regex}
        )
        return response.Response([{"name": value[0]} for value in result])
