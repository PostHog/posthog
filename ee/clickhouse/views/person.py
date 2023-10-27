from typing import Dict, List, Optional, Tuple

from rest_framework import request, response
from rest_framework.decorators import action

from ee.clickhouse.queries.funnels.funnel_correlation_persons import (
    FunnelCorrelationActors,
)
from posthog.api.person import PersonViewSet
from posthog.constants import (
    FUNNEL_CORRELATION_PERSON_LIMIT,
    FUNNEL_CORRELATION_PERSON_OFFSET,
    INSIGHT_FUNNELS,
)
from posthog.decorators import cached_by_filters
from posthog.models import Filter
from posthog.utils import format_query_params_absolute_url


class EnterprisePersonViewSet(PersonViewSet):
    @action(methods=["GET", "POST"], url_path="funnel/correlation", detail=False)
    def funnel_correlation(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        return self._respond_with_cached_results(self.calculate_funnel_correlation_persons(request))

    @cached_by_filters
    def calculate_funnel_correlation_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[List, Optional[str], Optional[str], int]]:
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        if not filter.correlation_person_limit:
            filter = filter.shallow_clone({FUNNEL_CORRELATION_PERSON_LIMIT: 100})
        base_uri = request.build_absolute_uri("/")
        actors, serialized_actors, raw_count = FunnelCorrelationActors(
            filter=filter, team=self.team, base_uri=base_uri
        ).get_actors()
        _should_paginate = raw_count >= filter.correlation_person_limit

        next_url = (
            format_query_params_absolute_url(
                request,
                filter.correlation_person_offset + filter.correlation_person_limit,
                offset_alias=FUNNEL_CORRELATION_PERSON_OFFSET,
                limit_alias=FUNNEL_CORRELATION_PERSON_LIMIT,
            )
            if _should_paginate
            else None
        )
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {
            "result": (
                serialized_actors,
                next_url,
                initial_url,
                raw_count - len(serialized_actors),
            )
        }


class LegacyEnterprisePersonViewSet(EnterprisePersonViewSet):
    legacy_team_compatibility = True
