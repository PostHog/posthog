import json

from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.database.schema.sessions import get_lazy_session_table_properties
from posthog.models.event.util import ClickhouseEventSerializer
from posthog.queries.property_values import get_session_column_values_for_key
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.utils import convert_property_value, flatten

QUERY_DEFAULT_EXPORT_LIMIT = 3_500


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


class SessionViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    # queryset = Session.objects.none() # not used
    scope_object = "query"
    renderer_classes = tuple(api_settings.DEFAULT_RENDERER_CLASSES) + (csvrenderers.PaginatedCSVRenderer,)
    serializer_class = ClickhouseEventSerializer
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    pagination_class = UncountedLimitOffsetPagination

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        team = self.team

        key = request.GET.get("key")
        search_term = request.GET.get("value")

        if not key:
            raise ValidationError(detail=f"Key not provided")

        result = get_session_column_values_for_key(key, team, search_term=search_term)

        flattened = []
        for value in result:
            try:
                # Try loading as json for dicts or arrays
                flattened.append(json.loads(value[0]))
            except json.decoder.JSONDecodeError:
                flattened.append(value[0])
        return response.Response([{"name": convert_property_value(value)} for value in flatten(flattened)])

    @action(methods=["GET"], detail=False)
    def property_definitions(self, request: request.Request, **kwargs) -> response.Response:
        search = request.GET.get("search")

        # unlike e.g. event properties, there's a very limited number of session properties,
        # so we can just return them all
        results = get_lazy_session_table_properties(search)
        return response.Response(
            {
                "count": len(results),
                "results": results,
            }
        )
