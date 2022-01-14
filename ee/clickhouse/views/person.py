import json
from typing import Callable, Dict, List, Optional, Tuple, Type, Union

from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnDict, ReturnList

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import delete_person
from ee.clickhouse.queries.funnels import ClickhouseFunnelActors, ClickhouseFunnelTrendsActors
from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from ee.clickhouse.queries.funnels.funnel_strict_persons import ClickhouseFunnelStrictActors
from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from ee.clickhouse.queries.paths import ClickhousePathsActors
from ee.clickhouse.queries.retention.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.stickiness.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from ee.clickhouse.sql.person import GET_PERSON_PROPERTIES_COUNT
from posthog.api.person import PersonViewSet
from posthog.constants import (
    FUNNEL_CORRELATION_PERSON_LIMIT,
    FUNNEL_CORRELATION_PERSON_OFFSET,
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    LIMIT,
    FunnelVizType,
)
from posthog.decorators import cached_function
from posthog.models import Event, Filter, Person
from posthog.models.filters.path_filter import PathFilter
from posthog.utils import format_query_params_absolute_url


def should_paginate(results, limit: Union[str, int]) -> bool:
    return len(results) > int(limit) - 1


def get_funnel_actor_class(filter: Filter) -> Callable:
    funnel_actor_class: Type[ClickhouseFunnelBase]
    if filter.funnel_viz_type == FunnelVizType.TRENDS:
        funnel_actor_class = ClickhouseFunnelTrendsActors
    else:
        if filter.funnel_order_type == "unordered":
            funnel_actor_class = ClickhouseFunnelUnorderedActors
        elif filter.funnel_order_type == "strict":
            funnel_actor_class = ClickhouseFunnelStrictActors
        else:
            funnel_actor_class = ClickhouseFunnelActors

    return funnel_actor_class


class ClickhousePersonViewSet(PersonViewSet):
    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    @action(methods=["GET", "POST"], detail=False)
    def funnel(self, request: Request, **kwargs) -> Response:
        if request.user.is_anonymous or not self.team:
            return Response(data=[])

        results_package = self.calculate_funnel_persons(request)

        if not results_package:
            return Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_funnel_persons(self, request: Request) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)
        if not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        funnel_actor_class = get_funnel_actor_class(filter)

        actors, serialized_actors = funnel_actor_class(filter, self.team).get_actors()
        _should_paginate = should_paginate(actors, filter.limit)
        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (serialized_actors, next_url, initial_url)}

    @action(methods=["GET", "POST"], url_path="funnel/correlation", detail=False)
    def funnel_correlation(self, request: Request, **kwargs) -> Response:
        if request.user.is_anonymous or not self.team:
            return Response(data=[])

        results_package = self.calculate_funnel_correlation_persons(request)

        if not results_package:
            return Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return Response(
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
        self, request: Request
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

    def get_properties(self, request: Request):
        rows = sync_execute(GET_PERSON_PROPERTIES_COUNT, {"team_id": self.team.pk})
        return [{"name": name, "count": count} for name, count in rows]

    @action(methods=["GET", "POST"], detail=False)
    def path(self, request: Request, **kwargs) -> Response:
        if request.user.is_anonymous or not self.team:
            return Response(data=[])

        results_package = self.calculate_path_persons(request)

        if not results_package:
            return Response(data=[])

        people, next_url, initial_url = results_package["result"]

        return Response(
            data={
                "results": [{"people": people, "count": len(people)}],
                "next": next_url,
                "initial": initial_url,
                "is_cached": results_package.get("is_cached"),
                "last_refresh": results_package.get("last_refresh"),
            }
        )

    @cached_function
    def calculate_path_persons(self, request: Request) -> Dict[str, Tuple[list, Optional[str], Optional[str]]]:
        if request.user.is_anonymous or not self.team:
            return {"result": ([], None, None)}

        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS}, team=self.team)
        if not filter.limit:
            filter = filter.with_data({LIMIT: 100})

        funnel_filter = None
        funnel_filter_data = request.GET.get("funnel_filter") or request.data.get("funnel_filter")
        if funnel_filter_data:
            if isinstance(funnel_filter_data, str):
                funnel_filter_data = json.loads(funnel_filter_data)
            funnel_filter = Filter(data={"insight": INSIGHT_FUNNELS, **funnel_filter_data}, team=self.team)

        people, serialized_actors = ClickhousePathsActors(filter, self.team, funnel_filter=funnel_filter).get_actors()
        _should_paginate = should_paginate(people, filter.limit)

        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        initial_url = format_query_params_absolute_url(request, 0)

        # cached_function expects a dict with the key result
        return {"result": (serialized_actors, next_url, initial_url)}

    def destroy(self, request: Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)
            delete_person(
                person.uuid, person.properties, person.is_identified, delete_events=True, team_id=self.team.pk
            )
            person.delete()
            return Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")


class LegacyClickhousePersonViewSet(ClickhousePersonViewSet):
    legacy_team_compatibility = True
