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

    @action(methods=["POST"], detail=False, url_path="slack/interactivity-callback")
    def slack_interactivity_callback(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # This is an empty endpoint for the Slack interactivity callback.
        # We don't verify the request, as we don't do anything with the submitted data.
        # We only use it to supress the warnings when users press buttons in Slack messages.
        # In case we decide to do something with it, please add the verification process here.
        return Response({"status": "ok"})

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
