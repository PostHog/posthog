from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request

from ...facade import diagnostics
from ...facade.diagnostics_contracts import ErrorNewCount
from .diagnostics_resource import RANGE_TOO_LONG_RESPONSE, SCOPE_RESPONSE, DiagnosticsViewSet
from .errors import ErrorSearchQuerySerializer
from .trace_resource import THROTTLED_RESPONSE


class ErrorNewCountViewSet(DiagnosticsViewSet):
    @validated_request(
        query_serializer=ErrorSearchQuerySerializer,
        responses={
            200: OpenApiResponse(response=ErrorNewCount),
            400: OpenApiResponse(description="A parameter, the date range or a property filter is invalid."),
            403: SCOPE_RESPONSE,
            422: RANGE_TOO_LONG_RESPONSE,
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_errors_new_count_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """How many errors of the errors list are new to the date range: they occurred in it and not in the 30 days
        before it. Send the filters and search of the list, so the two agree."""
        selection = self._selection(request)
        new_count = self._read(
            request,
            lambda user: diagnostics.count_new_errors(
                self.team, user, selection, search=request.validated_query_data.get("search")
            ),
        )
        return Response(new_count.model_dump(mode="json", by_alias=True))
