from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_request_analytics_properties
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner

from products.access_control.backend.facade.user_access_control import UserAccessControlError

WEB_VITALS_METRICS = ["INP", "LCP", "CLS", "FCP"]


class WebVitalsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Get web vitals for a specific pathname.
    Toolbar accesses this via OAuth (handled by TeamAndOrgViewSetMixin.get_authenticators).
    """

    scope_object = "query"

    @extend_schema(
        parameters=[
            OpenApiParameter("pathname", OpenApiTypes.STR, description="Filter web vitals by pathname", required=True),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def list(self, request: Request, *args, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        pathname = request.query_params.get("pathname")
        if not pathname:
            raise exceptions.ValidationError({"pathname": "This field is required."})

        query_runner = get_query_runner(
            query={
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d", "explicitDate": False},
                "filterTestAccounts": False,
                "interval": "week",
                "properties": [
                    {"type": "event", "key": "$pathname", "operator": "is_cleaned_path_exact", "value": [pathname]}
                ],
                # The toolbar's webVitalsToolbarLogic.ts finds each metric by its row's `order`, so keep this order
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "$web_vitals",
                        "name": metric,
                        "custom_name": metric,
                        "math": "p90",
                        "math_property": f"$web_vitals_{metric}_value",
                    }
                    for metric in WEB_VITALS_METRICS
                ],
                "trendsFilter": {
                    "display": "ActionsLineGraph",
                },
            },
            team=self.team,
        )

        try:
            result = query_runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                analytics_props=get_request_analytics_properties(request),
            )
        except UserAccessControlError as e:
            raise ValidationError(str(e))

        if result is None:
            return Response({"error": "Failed to calculate web vitals"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = result.model_dump(mode="json")
        # posthog-js pins the toolbar to the SDK release, so customer sites keep running old toolbar code
        # until they upgrade the SDK. Older toolbars find each metric by `action.custom_name` and throw
        # when `action` is missing, so this field must stay while those SDK versions are in use.
        for row in response["results"]:
            row["action"] = {"custom_name": WEB_VITALS_METRICS[row["order"]]}

        return Response(response, status=status.HTTP_200_OK)
