import json

from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.database.schema.sessions import get_lazy_session_table_properties, get_lazy_session_table_values
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.utils import convert_property_value, flatten


class SessionViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    scope_object = "query"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        team = self.team

        key = request.GET.get("key")
        search_term = request.GET.get("value")

        if not key:
            raise ValidationError(detail=f"Key not provided")

        result = get_lazy_session_table_values(key, search_term=search_term, team=team)

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
