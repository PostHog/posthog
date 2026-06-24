from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import get_request_analytics_properties
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.rbac.user_access_control import UserAccessControlError


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

        try:
            result = query_runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                analytics_props=get_request_analytics_properties(request),
            )
        except UserAccessControlError as e:
            raise ValidationError(str(e))
        except Exception as e:
            # This powers a non-critical background fetch in the toolbar that degrades gracefully to
            # "no data". A transient query-runner failure shouldn't surface as a 500 — capture it for
            # visibility and return an empty result so the toolbar simply shows no metrics.
            capture_exception(e)
            return Response({"results": []}, status=status.HTTP_200_OK)

        if result is None:
            return Response({"results": []}, status=status.HTTP_200_OK)

        return Response(result.model_dump(mode="json"), status=status.HTTP_200_OK)
