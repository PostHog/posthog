import json
from typing import Any, Dict, Type

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries import ClickhousePaths
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels import (
    ClickhouseFunnel,
    ClickhouseFunnelBase,
    ClickhouseFunnelStrict,
    ClickhouseFunnelTimeToConvert,
    ClickhouseFunnelTrends,
    ClickhouseFunnelUnordered,
)
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.sessions.clickhouse_sessions import ClickhouseSessions
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.util import get_earliest_timestamp
from posthog.api.insight import InsightViewSet
from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_PATHS,
    INSIGHT_SESSIONS,
    INSIGHT_STICKINESS,
    PATHS_INCLUDE_EVENT_TYPES,
    TRENDS_STICKINESS,
    FunnelOrderType,
    FunnelVizType,
)
from posthog.decorators import cached_function
from posthog.models.filters import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter


class ClickhouseInsightsViewSet(InsightViewSet):
    @cached_function
    def calculate_trends(self, request: Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=self.team)

        if filter.insight == INSIGHT_STICKINESS or filter.shown_as == TRENDS_STICKINESS:
            stickiness_filter = StickinessFilter(
                request=request, team=team, get_earliest_timestamp=get_earliest_timestamp
            )
            result = ClickhouseStickiness().run(stickiness_filter, team)
        else:
            trends_query = ClickhouseTrends()
            result = trends_query.run(filter, team)

        self._refresh_dashboard(request=request)
        return {"result": result}

    @cached_function
    def calculate_session(self, request: Request) -> Dict[str, Any]:
        return {
            "result": ClickhouseSessions().run(
                team=self.team,
                filter=SessionsFilter(request=request, data={"insight": INSIGHT_SESSIONS}, team=self.team),
            )
        }

    @cached_function
    def calculate_path(self, request: Request) -> Dict[str, Any]:
        team = self.team
        filter = PathFilter(request=request, data={"insight": INSIGHT_PATHS}, team=self.team)

        funnel_filter = None
        funnel_filter_data = request.GET.get("funnel_filter") or request.data.get("funnel_filter")
        if funnel_filter_data:
            if isinstance(funnel_filter_data, str):
                funnel_filter_data = json.loads(funnel_filter_data)
            funnel_filter = Filter(data={"insight": INSIGHT_FUNNELS, **funnel_filter_data}, team=self.team)

        #  backwards compatibility
        if filter.path_type:
            filter = filter.with_data({PATHS_INCLUDE_EVENT_TYPES: [filter.path_type]})
        resp = ClickhousePaths(filter=filter, team=team, funnel_filter=funnel_filter).run()

        return {"result": resp}

    @cached_function
    def calculate_funnel(self, request: Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request, data={"insight": INSIGHT_FUNNELS}, team=self.team)

        funnel_order_class: Type[ClickhouseFunnelBase] = ClickhouseFunnel
        if filter.funnel_order_type == FunnelOrderType.UNORDERED:
            funnel_order_class = ClickhouseFunnelUnordered
        elif filter.funnel_order_type == FunnelOrderType.STRICT:
            funnel_order_class = ClickhouseFunnelStrict

        if filter.funnel_viz_type == FunnelVizType.TRENDS:
            return {
                "result": ClickhouseFunnelTrends(team=team, filter=filter, funnel_order_class=funnel_order_class).run()
            }
        elif filter.funnel_viz_type == FunnelVizType.TIME_TO_CONVERT:
            return {
                "result": ClickhouseFunnelTimeToConvert(
                    team=team, filter=filter, funnel_order_class=funnel_order_class
                ).run()
            }
        else:
            return {"result": funnel_order_class(team=team, filter=filter).run()}

    # ******************************************
    # /projects/:id/insights/funnel/correlation
    #
    # params:
    # - params are the same as for funnel
    #
    # Returns significant events, i.e. those that are correlated with a person
    # making it through a funnel
    # ******************************************
    @action(methods=["GET", "POST"], url_path="funnel/correlation", detail=False)
    def funnel_correlation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        result = self.calculate_funnel_correlation(request)
        return Response(result)

    @cached_function
    def calculate_funnel_correlation(self, request: Request) -> Dict[str, Any]:
        team = self.team
        filter = Filter(request=request)

        result = FunnelCorrelation(filter=filter, team=team).run()

        return {"result": result}

    @cached_function
    def calculate_retention(self, request: Request) -> Dict[str, Any]:
        team = self.team
        data = {}
        if not request.GET.get("date_from"):
            data.update({"date_from": "-11d"})
        filter = RetentionFilter(data=data, request=request, team=self.team)
        result = ClickhouseRetention().run(filter, team)
        return {"result": result}


class LegacyClickhouseInsightsViewSet(ClickhouseInsightsViewSet):
    legacy_team_compatibility = True
