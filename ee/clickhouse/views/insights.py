from abc import ABC, abstractmethod
from typing import Any

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.clickhouse_trends import ClickhouseTrends
from posthog.api.insight import InsightViewSet
from posthog.constants import TRENDS_STICKINESS
from posthog.models.filter import Filter


class InsightInterface(ABC):
    @abstractmethod
    def trend(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def session(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def funnel(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def retention(self, request: Request, *args: Any, **kwargs: Any):
        pass

    @abstractmethod
    def path(self, request: Request, *args: Any, **kwargs: Any):
        pass


class ClickhouseInsights(InsightViewSet, InsightInterface):
    @action(methods=["GET"], detail=False)
    def trend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.team_set.get()
        filter = Filter(request=request)

        if filter.shown_as == TRENDS_STICKINESS:
            result = []
        else:
            result = ClickhouseTrends().run(filter, team)

        self._refresh_dashboard(request=request)

        return Response(result)
