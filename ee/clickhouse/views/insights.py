from typing import Any, Dict

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from posthog.api.insight import InsightViewSet
from posthog.decorators import cached_function
from posthog.models.filters import Filter


class ClickhouseInsightsViewSet(InsightViewSet):
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

        base_uri = request.build_absolute_uri("/")
        result = FunnelCorrelation(filter=filter, team=team, base_uri=base_uri).run()

        return {"result": result}
