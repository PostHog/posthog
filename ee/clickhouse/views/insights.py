from typing import Any

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
from posthog.models import Event
from posthog.models.filters import Filter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter


class ClickhouseInsightsViewSet(InsightViewSet):
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = self.team
        filter = Filter(request=request)

        if filter.shown_as == TRENDS_STICKINESS:
            filter = StickinessFilter(request=request, team=team, get_earliest_timestamp=get_earliest_timestamp)
            result = ClickhouseStickiness().run(filter, team)
        else:
            result = ClickhouseTrends().run(filter, team)

        self._refresh_dashboard(request=request)

        return Response(result)

    @action(methods=["GET"], detail=False)
    def session(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = ClickhouseSessions().run(
            team=self.team, filter=Filter(request=request, data={"insight": INSIGHT_SESSIONS})
        )

        return Response({"result": response,})

    @action(methods=["GET"], detail=False)
    def path(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_PATHS})
        resp = ClickhousePaths().run(filter=filter, team=team)
        return Response(resp)

    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS})
        response = ClickhouseFunnel(team=team, filter=filter).run()
        return Response(response)

    @action(methods=["GET"], detail=False)
    def retention(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        team = self.team
        filter = RetentionFilter(request=request)
        result = ClickhouseRetention().run(filter, team)
        return Response({"data": result})
