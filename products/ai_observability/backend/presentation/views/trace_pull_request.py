from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.permissions import PostHogFeatureFlagPermission

from products.engineering_analytics.backend.facade.contracts import ENGINEERING_ANALYTICS_FEATURE_FLAG

from ...facade import api, contracts
from .trace_ids import MalformedTraceIdSegmentError, decode_trace_id_segment
from .trace_resource import THROTTLED_RESPONSE, TRACE_ID_PARAMETER, TraceQuerySerializer, TraceResourceViewSet


class TracePullRequestViewSet(TraceResourceViewSet):
    # The read opens engineering analytics data, so a key needs that product's scope as well.
    required_scopes = ["llm_analytics:read", "engineering_analytics:read"]
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = ENGINEERING_ANALYTICS_FEATURE_FLAG

    @validated_request(
        query_serializer=TraceQuerySerializer,
        parameters=[TRACE_ID_PARAMETER],
        responses={
            200: OpenApiResponse(response=contracts.TracePullRequestLookup),
            400: OpenApiResponse(description="The timestamp hint or the encoded trace id is malformed."),
            403: OpenApiResponse(
                description="The engineering-analytics feature flag is off for the project, or the API key lacks a scope."
            ),
            429: THROTTLED_RESPONSE,
        },
        operation_id="ai_observability_traces_pull_request_retrieve",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The pull request the trace's git branch belongs to, from engineering analytics."""
        try:
            trace_id = decode_trace_id_segment(self.trace_segment)
        except MalformedTraceIdSegmentError:
            return Response({"detail": "Malformed encoded trace id."}, status=status.HTTP_400_BAD_REQUEST)
        lookup = self._read(
            request,
            lambda user, hint: api.get_trace_pull_request(self.team, user, self.user_access_control, trace_id, hint),
        )
        return Response(lookup.model_dump(mode="json", by_alias=True))
