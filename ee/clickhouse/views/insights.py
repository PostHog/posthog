from typing import Any, Dict, List

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.queries.sessions.list import SESSIONS_LIST_DEFAULT_LIMIT
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL
from posthog.api.insight import InsightViewSet
from posthog.constants import TRENDS_STICKINESS
from posthog.decorators import CacheType, cached_function
from posthog.models import Event
from posthog.models.filters import Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter


class ClickhouseInsightsViewSet(InsightViewSet):
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_trends(request)
        return Response(result)

    @cached_function(cache_type=CacheType.TRENDS)
    def calculate_trends(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request)

        if filter.shown_as == TRENDS_STICKINESS:
            filter = StickinessFilter(request=request, team=team, get_earliest_timestamp=get_earliest_timestamp)
            result = ClickhouseStickiness().run(filter, team)
        else:
            result = ClickhouseTrends().run(filter, team)

        self._refresh_dashboard(request=request)
        return result

    @action(methods=["GET"], detail=False)
    def session(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = self.team
        filter = Filter(request=request)

        limit = int(request.GET.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(request.GET.get("offset", 0))

        response = ClickhouseSessions().run(team=team, filter=filter, limit=limit + 1, offset=offset)

        if "distinct_id" in request.GET and request.GET["distinct_id"]:
            try:
                person_ids = get_persons_by_distinct_ids(team.pk, [request.GET["distinct_id"]])[0].distinct_ids
                response = [session for i, session in enumerate(response) if response[i]["distinct_id"] in person_ids]
            except IndexError:
                response = []

        if len(response) > limit:
            response.pop()
            return Response({"result": response, "offset": offset + limit})
        else:
            return Response({"result": response,})

    @action(methods=["GET"], detail=False)
    def path(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        resp = self.calculate_paths(request)
        return Response(resp)

    @cached_function(cache_type=CacheType.TRENDS)
    def calculate_paths(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request)
        result = ClickhousePaths().run(filter=filter, team=team)
        return result

    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_funnel(request)
        return Response(result)

    @cached_function(cache_type=CacheType.TRENDS)
    def calculate_funnel(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request)
        result = ClickhouseFunnel(team=team, filter=filter).run()
        return result

    @action(methods=["GET"], detail=False)
    def retention(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_retention(request)
        return Response({"data": result})

    @cached_function(cache_type=CacheType.TRENDS)
    def calculate_retention(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = RetentionFilter(request=request)
        result = ClickhouseRetention().run(filter, team)
        return result
