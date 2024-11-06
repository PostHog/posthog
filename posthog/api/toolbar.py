from django.conf import settings
from typing import Any

from rest_framework import viewsets, request, response, serializers, status

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import TemporaryTokenAuthentication  # , PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.rate_limit import ClickHouseSustainedRateThrottle, ClickHouseBurstRateThrottle


class ToolbarResponseSerializer(serializers.Serializer):
    site_url = serializers.CharField(required=True)


class ToolbarViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = ToolbarResponseSerializer

    authentication_classes = [
        # SessionAuthentication,
        # PersonalAPIKeyAuthentication,
        TemporaryTokenAuthentication
    ]

    @action(methods=["GET"], detail=False)
    def info(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        response_serializer = ToolbarResponseSerializer(
            data={
                "site_url": settings.SITE_URL,
            }
        )
        response_serializer.is_valid(raise_exception=True)
        return response.Response(response_serializer.data, status=status.HTTP_200_OK)
