from typing import Any

from posthog.api.utils import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.paths import ClickhousePaths
from ee.clickhouse.queries.retention import ClickhouseRetention
from ee.clickhouse.queries.stickiness import ClickhouseStickiness
from posthog.api.insight import InsightViewSet
from posthog.decorators import cached_by_filters
from posthog.models import Insight
from posthog.models.dashboard import Dashboard
from posthog.models.filters import Filter


class CanEditInsight(BasePermission):
    message = "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."

    def has_object_permission(self, request: Request, view, insight: Insight) -> bool:
        if request.method in SAFE_METHODS:
            return True

        return view.user_permissions.insight(insight).effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT


class ClickhouseInsightsViewSet(InsightViewSet):
    permission_classes = [CanEditInsight]
    retention_query_class = ClickhouseRetention
    stickiness_query_class = ClickhouseStickiness
    paths_query_class = ClickhousePaths

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

    @cached_by_filters
    def calculate_funnel_correlation(self, request: Request) -> dict[str, Any]:
        team = self.team
        filter = Filter(request=request, team=team)

        base_uri = request.build_absolute_uri("/")
        result = FunnelCorrelation(filter=filter, team=team, base_uri=base_uri).run()

        return {"result": result}
