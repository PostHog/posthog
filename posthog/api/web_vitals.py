from rest_framework import viewsets, exceptions, status
from rest_framework.response import Response
from rest_framework.request import Request
from posthog.api.routing import TeamAndOrgViewSetMixin
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from posthog.hogql_queries.query_runner import get_query_runner, ExecutionMode


class WebVitalsViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "web_vitals"

    """
    Get web vitals for a specific pathname.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter("pathname", OpenApiTypes.STR, description="Filter web vitals by pathname", required=True),
        ]
    )
    def list(self, request: Request, *args, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        pathname = request.query_params.get("pathname")

        query_runner = get_query_runner(
            query={
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                # TODO: Needs to merge with my other PR (@rafaaudibert) and use the path-cleaned event in here
                "properties": [{"type": "event", "key": "$pathname", "operator": "exact", "value": [pathname]}],
                "series": [
                    {
                        "event": "$web_vitals",
                        "name": "INP",
                        "custom_name": "INP",
                        "math": "p90",
                        "math_property": "$web_vitals_INP_value",
                    },
                    {
                        "event": "$web_vitals",
                        "name": "LCP",
                        "custom_name": "LCP",
                        "math": "p90",
                        "math_property": "$web_vitals_LCP_value",
                    },
                    {
                        "event": "$web_vitals",
                        "name": "CLS",
                        "custom_name": "CLS",
                        "math": "p90",
                        "math_property": "$web_vitals_CLS_value",
                    },
                    {
                        "event": "$web_vitals",
                        "name": "FCP",
                        "custom_name": "FCP",
                        "math": "p90",
                        "math_property": "$web_vitals_FCP_value",
                    },
                ],
                "trendsFilter": {
                    "display": "ActionsLineGraph",
                },
            },
            team=self.team,
        )

        # TODO: Change to RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        # This is only the best one while developing and testing locally
        result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert result is not None

        return Response(result.model_dump(mode="json"), status=status.HTTP_200_OK)
