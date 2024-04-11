from typing import Any

from rest_framework import viewsets, request, response, serializers, status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.hogql.ast import Constant
from posthog.hogql.query import execute_hogql_query
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle


class HeatmapResponseItemSerializer(serializers.Serializer):
    count = serializers.IntegerField(required=True)
    pointer_y = serializers.IntegerField(required=True)
    pointer_relative_x = serializers.FloatField(required=True)
    pointer_target_fixed = serializers.BooleanField(required=True)


class HeatmapsRequestSerializer(serializers.Serializer):
    viewport_min_width = serializers.IntegerField(required=False)
    viewport_max_width = serializers.IntegerField(required=False)
    type = serializers.CharField(required=False)
    date_from = serializers.CharField(required=False)
    date_to = serializers.CharField(required=False)
    url_exact = serializers.CharField(required=False)
    url_pattern = serializers.CharField(required=False)


class HeatmapsResponseSerializer(serializers.Serializer):
    results: serializers.ListSerializer = HeatmapResponseItemSerializer(many=True)


class HeatmapViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "heatmaps"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = HeatmapsResponseSerializer

    def get_queryset(self):
        return None

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        request_serializer = HeatmapsRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        doohickies = execute_hogql_query(
            """
            select *, count() as cnt
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

        data = [
            {
                "pointer_target_fixed": item[0],
                "pointer_relative_x": item[1],
                "pointer_y": item[2],
                "count": item[3],
            }
            for item in doohickies.results
        ]

        response_serializer = HeatmapsResponseSerializer(data={"results": data})
        response_serializer.is_valid(raise_exception=True)
        return response.Response(response_serializer.data, status=status.HTTP_200_OK)
