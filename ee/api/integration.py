from typing import Any

from rest_framework import viewsets
from posthog.api.utils import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response

from ee.tasks.slack import handle_slack_event
from posthog.api.integration import IntegrationSerializer
from posthog.models.integration import (
    Integration,
    SlackIntegration,
    SlackIntegrationError,
)


class PublicIntegrationViewSet(viewsets.GenericViewSet):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    authentication_classes = []
    permission_classes = []

    @action(methods=["POST"], detail=False, url_path="slack/events")
    def slack_events(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            SlackIntegration.validate_request(request)
        except SlackIntegrationError:
            raise AuthenticationFailed()

        if request.data["type"] == "url_verification":
            return Response({"challenge": request.data["challenge"]})

        handle_slack_event(request.data)

        return Response({"status": "ok"})
