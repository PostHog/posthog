from typing import Any

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.queries.clickhouse_paths import ClickhousePaths
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_sessions import SESSIONS_LIST_DEFAULT_LIMIT, ClickhouseSessions
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import (
    CH_FUNNEL_ENDPOINT,
    CH_PATH_ENDPOINT,
    CH_RETENTION_ENDPOINT,
    CH_SESSION_ENDPOINT,
    CH_TREND_ENDPOINT,
    endpoint_enabled,
)
from posthog.api.insight import InsightViewSet
from posthog.constants import TRENDS_STICKINESS
from posthog.models.filter import Filter


class ClickhouseInsights(InsightViewSet):
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not endpoint_enabled(CH_TREND_ENDPOINT, request.user.distinct_id):
            result = super().calculate_trends(request)
            return Response(result)

        team = request.user.team_set.get()
        filter = Filter(request=request)

        if filter.shown_as == TRENDS_STICKINESS:
            result = ClickhouseStickiness().run(filter, team)
        else:
            result = ClickhouseTrends().run(filter, team)

        self._refresh_dashboard(request=request)

        return Response(result)

    @action(methods=["GET"], detail=False)
    def session(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not endpoint_enabled(CH_SESSION_ENDPOINT, request.user.distinct_id):
            result = super().calculate_session(request)
            return Response(result)

        team = request.user.team_set.get()
        filter = Filter(request=request)

        limit = int(request.GET.get("limit", SESSIONS_LIST_DEFAULT_LIMIT))
        offset = int(request.GET.get("offset", 0))

        response = ClickhouseSessions().run(team=team, filter=filter, limit=limit + 1, offset=offset)

        if len(response) > limit:
            response.pop()
            return Response({"result": response, "offset": offset + limit})
        else:
            return Response({"result": response,})

    @action(methods=["GET"], detail=False)
    def path(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        if not endpoint_enabled(CH_PATH_ENDPOINT, request.user.distinct_id):
            result = super().calculate_path(request)
            return Response(result)

        team = request.user.team_set.get()
        filter = Filter(request=request)
        resp = ClickhousePaths().run(filter=filter, team=team)
        return Response(resp)

    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        if not endpoint_enabled(CH_FUNNEL_ENDPOINT, request.user.distinct_id):
            result = super().calculate_funnel(request)
            return Response(result)

        team = request.user.team_set.get()
        filter = Filter(request=request)
        response = ClickhouseFunnel(team=team, filter=filter).run()
        return Response(response)

    @action(methods=["GET"], detail=False)
    def retention(self, request: Request, *args: Any, **kwargs: Any) -> Response:

        if not endpoint_enabled(CH_RETENTION_ENDPOINT, request.user.distinct_id):
            result = super().calculate_retention(request)
            return Response({"data": result})

        team = request.user.team_set.get()
        filter = Filter(request=request)
        result = ClickhouseRetention().run(filter, team)
        return Response({"data": result})
