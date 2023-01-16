from functools import lru_cache

import posthoganalytics
from rest_framework import authentication, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from statshog.defaults.django import statsd

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication, TemporaryTokenAuthentication
from posthog.client import sync_execute
from posthog.models import Element, Filter
from posthog.models.element.element import chain_to_elements
from posthog.models.element.sql import (
    GET_ELEMENTS,
    GET_ELEMENTS_FROM_MV,
    GET_NUMBER_OF_DAYS_IN_ELEMENTS_CHAIN_DAILY_COUNTS,
    GET_VALUES,
)
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
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


class ElementViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    filter_rewrite_rules = {"team_id": "group__team_id"}

    queryset = Element.objects.all()
    serializer_class = ElementSerializer
    authentication_classes = [
        TemporaryTokenAuthentication,
        PersonalAPIKeyAuthentication,
        authentication.SessionAuthentication,
        authentication.BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    include_in_docs = False

    @action(methods=["GET"], detail=False)
    def stats(self, request: request.Request, **kwargs) -> response.Response:
        current_url_property_filter = Filter(request=request, team=self.team)

        date_params = {}
        query_date_range = QueryDateRange(filter=current_url_property_filter, team=self.team, should_round=True)
        date_from, date_from_params = query_date_range.date_from
        date_to, date_to_params = query_date_range.date_to
        date_params.update(date_from_params)
        date_params.update(date_to_params)

        try:
            limit = int(request.query_params.get("limit", 100))
        except ValueError:
            raise ValidationError("Limit must be an integer")

        try:
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            raise ValidationError("offset must be an integer")

        paginate_response = request.query_params.get("paginate_response", "false") == "true"
        if not paginate_response:
            # once we are getting no hits on this counter we can default to paginated responses
            statsd.incr("toolbar_element_stats_unpaginated_api_request_tombstone", tags={"team_id": self.team_id})

        prop_filters, prop_filter_params = parse_prop_grouped_clauses(
            team_id=self.team.pk, property_group=current_url_property_filter.property_groups
        )

        can_use_materialized_view_for_this_date_range = self.materialized_view_has_enough_data(
            query_date_range.num_intervals, self.team_id
        )
        flag_is_enabled = posthoganalytics.feature_enabled(
            "elements_chain_daily_counts_materialized_view", self.team.pk
        )

        if can_use_materialized_view_for_this_date_range and flag_is_enabled:
            # this API only supports two filters
            # an exact match on current url or a regex match on current url
            current_url_property_filter = current_url_property_filter.property_groups.values[0]
            operator = current_url_property_filter.operator
            value = current_url_property_filter.value
            current_url_params = {"current_url": value}
            if operator == "exact":
                current_url_query = f'"$current_url" = %(current_url)s'
            elif operator == "regex":
                current_url_query = f'match("$current_url",%(current_url)s)'
            else:
                raise ValidationError(detail="Invalid operator for current_url filter: " + operator)

            result = sync_execute(
                GET_ELEMENTS_FROM_MV.format(current_url_query=current_url_query),
                {
                    "team_id": self.team.pk,
                    **date_params,
                    **current_url_params,
                },
            )
        else:
            result = sync_execute(
                GET_ELEMENTS.format(
                    date_from=date_from,
                    date_to=date_to,
                    query=prop_filters,
                    limit=limit,
                    conditional_offset=f" OFFSET {offset}" if paginate_response else "",
                ),
                {
                    "team_id": self.team.pk,
                    "timezone": self.team.timezone,
                    **prop_filter_params,
                    **date_params,
                },
            )
        serialized_elements = [
            {
                "count": elements[1],
                "hash": None,
                "elements": [ElementSerializer(element).data for element in chain_to_elements(elements[0])],
            }
            for elements in result
        ]

        if paginate_response:
            has_next = len(serialized_elements) > 0
            next_url = format_query_params_absolute_url(request, offset + limit) if has_next else None
            previous_url = format_query_params_absolute_url(request, offset - limit) if offset - limit >= 0 else None

            return response.Response({"results": serialized_elements, "next": next_url, "previous": previous_url})
        else:
            return response.Response(serialized_elements)

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
            GET_VALUES.format(), {"team_id": self.team.id, "regex": select_regex, "filter_regex": filter_regex}
        )
        return response.Response([{"name": value[0]} for value in result])

    @lru_cache(maxsize=1000)
    def materialized_view_has_enough_data(self, number_of_days: int, team_id: int) -> bool:
        """
        Rather than fill the materialized view,
        we check if it has enough data before using it for heatmaps of that size
        """
        result = sync_execute(GET_NUMBER_OF_DAYS_IN_ELEMENTS_CHAIN_DAILY_COUNTS, {"team_id": team_id})
        return result[0][0] + 1 > number_of_days


class LegacyElementViewSet(ElementViewSet):
    legacy_team_compatibility = True
