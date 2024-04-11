from typing import Any

from rest_framework import viewsets, request, response, serializers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.ast import Constant
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle


class HeatmapsResponseSerializer(serializers.Serializer):
    pass


class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "heatmaps"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapsResponseSerializer

    def get_queryset(self):
        return None

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        doohickies = execute_hogql_query(
            """
            select *, count()
            from (
                     select `$pointer_target_fixed`, round((x / `$viewport_width`), 2) as relative_client_x,
                            y * scale_factor                  as client_y
                     from heatmaps
                     where ceil(`$viewport_width` / 16) == ceil(1512 / 16)
                       and `$current_url` like '%'
                     and team_id = {team_id}
                     )
            group by `$pointer_target_fixed`, relative_client_x, client_y
            """,
            placeholders={"team_id": Constant(value=self.team.pk)},
            team=self.team,
        )
        return response.Response(doohickies.results)
