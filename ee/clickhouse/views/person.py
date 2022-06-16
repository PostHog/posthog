from typing import Callable, Dict, Optional, Tuple, Type

from rest_framework import request, response
from rest_framework.decorators import action

from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from posthog.api.person import PersonViewSet, should_paginate
from posthog.constants import (
    FUNNEL_CORRELATION_PERSON_LIMIT,
    FUNNEL_CORRELATION_PERSON_OFFSET,
    INSIGHT_FUNNELS,
    FunnelVizType,
)
from posthog.decorators import cached_function
from posthog.models import Filter
from posthog.queries.actor_base_query import ActorBaseQuery
from posthog.queries.funnels.funnel_persons import ClickhouseFunnelActors
from posthog.queries.funnels.funnel_strict_persons import ClickhouseFunnelStrictActors
from posthog.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsActors
from posthog.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from posthog.utils import format_query_params_absolute_url


def _get_funnel_actor_class_ee(filter: Filter) -> Callable:
    funnel_actor_class: Type[ActorBaseQuery]

    if filter.correlation_person_entity:
        funnel_actor_class = FunnelCorrelationActors
    elif filter.funnel_viz_type == FunnelVizType.TRENDS:
        funnel_actor_class = ClickhouseFunnelTrendsActors
    else:
        if filter.funnel_order_type == "unordered":
            funnel_actor_class = ClickhouseFunnelUnorderedActors
        elif filter.funnel_order_type == "strict":
            funnel_actor_class = ClickhouseFunnelStrictActors
        else:
            funnel_actor_class = ClickhouseFunnelActors

    return funnel_actor_class


class EnterprisePersonViewSet(PersonViewSet):
    @action(methods=["GET", "POST"], url_path="funnel/correlation", detail=False)
    def funnel_correlation(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not self.team:
            return response.Response(data=[])

        results_package = self.calculate_funnel_correlation_persons(request)

        if not results_package:
            return response.Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return response.Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_funnel_correlation_persons(
        self, request: request.Request
    ) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        if not filter.correlation_person_limit:
            filter = filter.with_data({FUNNEL_CORRELATION_PERSON_LIMIT: 100})
        base_uri = request.build_absolute_uri("/")
        actors, serialized_actors = FunnelCorrelationActors(
            filter=filter, team=self.team, base_uri=base_uri
        ).get_actors()
        _should_paginate = should_paginate(actors, filter.correlation_person_limit)

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
        return {"result": (serialized_actors, next_url, initial_url)}
