import json

from opentelemetry import trace
from rest_framework import request, response, viewsets
from rest_framework.exceptions import ValidationError

from posthog.schema import SessionTableVersion

from posthog.hogql.database.schema.sessions_v1 import (
    get_lazy_session_table_properties_v1,
    get_lazy_session_table_values_v1,
)
from posthog.hogql.database.schema.sessions_v2 import (
    get_lazy_session_table_properties_v2,
    get_lazy_session_table_values_v2,
)
from posthog.hogql.database.schema.sessions_v3 import (
    get_lazy_session_table_properties_v3,
    get_lazy_session_table_values_v3,
)
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.api.property_value_metrics import PROPERTY_VALUES_DURATION
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.utils import convert_property_value, flatten

tracer = trace.get_tracer(__name__)


class SessionViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
):
    scope_object = "query"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    scope_object_read_actions = ["property_definitions", "values"]

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs) -> response.Response:
        with (
            PROPERTY_VALUES_DURATION.labels(endpoint_type="session").time(),
            tracer.start_as_current_span("session_api_property_values") as span,
        ):
            team = self.team

            key = request.GET.get("key")
            search_term = request.GET.get("value")

            if not key:
                raise ValidationError(detail=f"Key not provided")

            span.set_attribute("team_id", team.pk)
            span.set_attribute("property_key", key)
            span.set_attribute("has_search_term", search_term is not None)

            modifiers = create_default_modifiers_for_team(team)
            version = modifiers.sessionTableVersion

            if version == SessionTableVersion.V3:
                span.set_attribute("session_table_version", "v3")
                result = get_lazy_session_table_values_v3(key, search_term=search_term, team=team)
            elif version == SessionTableVersion.V2 or version == SessionTableVersion.AUTO:
                span.set_attribute("session_table_version", "v2")
                result = get_lazy_session_table_values_v2(key, search_term=search_term, team=team)
            else:
                span.set_attribute("session_table_version", "v1")
                result = get_lazy_session_table_values_v1(key, search_term=search_term, team=team)

            span.set_attribute("result_count", len(result))

            flattened = []
            for value in result:
                try:
                    # Try loading as json for dicts or arrays
                    flattened.append(json.loads(value[0]))
                except json.decoder.JSONDecodeError:
                    flattened.append(value[0])

            return response.Response(
                {
                    "results": [{"name": convert_property_value(value)} for value in flatten(flattened)],
                    "refreshing": False,
                }
            )

    @action(methods=["GET"], detail=False)
    def property_definitions(self, request: request.Request, **kwargs) -> response.Response:
        search = request.GET.get("search")
        is_numerical = request.GET.get("is_numerical")

        # unlike e.g. event properties, there's a very limited number of session properties,
        # so we can just return them all
        modifiers = create_default_modifiers_for_team(self.team)
        version = modifiers.sessionTableVersion
        if version == SessionTableVersion.V3:
            results = get_lazy_session_table_properties_v3(search)
        elif version == SessionTableVersion.V2 or version == SessionTableVersion.AUTO:
            results = get_lazy_session_table_properties_v2(search)
        else:
            results = get_lazy_session_table_properties_v1(search)

        if is_numerical is not None:
            want_numerical = is_numerical.lower() == "true"
            results = [r for r in results if r.get("is_numerical") == want_numerical]

        return response.Response(
            {
                "count": len(results),
                "results": results,
            }
        )
