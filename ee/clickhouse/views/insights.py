from typing import Any, Dict, List

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.util import get_earliest_timestamp
from posthog.api.insight import InsightViewSet
from posthog.constants import INSIGHT_FUNNELS, INSIGHT_PATHS, INSIGHT_SESSIONS, TRENDS_STICKINESS
from posthog.decorators import cached_function
from posthog.models import Event
from posthog.models.filters import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter


class ClickhouseInsightsViewSet(InsightViewSet):
    @cached_function()
    def calculate_trends(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request)

        if filter.shown_as == TRENDS_STICKINESS:
            earliest_timestamp_func = lambda team_id: get_earliest_timestamp(team_id)
            stickiness_filter = StickinessFilter(
                request=request, team=team, get_earliest_timestamp=earliest_timestamp_func
            )
            result = ClickhouseStickiness().run(stickiness_filter, team)
        else:
            result = ClickhouseTrends().run(filter, team)

        self._refresh_dashboard(request=request)
        return result

    @cached_function()
    def calculate_session(self, request: Request) -> List[Dict[str, Any]]:
        return ClickhouseSessions().run(
            team=self.team, filter=SessionsFilter(request=request, data={"insight": INSIGHT_SESSIONS})
        )

    @cached_function()
    def calculate_path(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS})
        resp = ClickhousePaths().run(filter=filter, team=team)
        return resp

    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = self.calculate_funnel(request)
        return Response(response)

    @cached_function()
    def calculate_funnel(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS})
        return ClickhouseFunnel(team=team, filter=filter).run()

    @cached_function()
    def calculate_retention(self, request: Request) -> List[Dict[str, Any]]:
        team = self.team
        data = {}
        if not request.GET.get("date_from"):
            data.update({"date_from": "-11d"})
        filter = RetentionFilter(data=data, request=request)
        result = ClickhouseRetention().run(filter, team)
        return result
