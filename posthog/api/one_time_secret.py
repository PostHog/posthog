from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import SessionAuthentication
from posthog.models import User
from posthog.one_time_secret import consume_one_time_secret, peek_one_time_secret

_UNAVAILABLE_MESSAGE = "This secret link has expired or has already been revealed."


class OneTimeSecretSerializer(serializers.Serializer):
    secret_type = serializers.CharField(
        help_text="The kind of secret this link reveals, e.g. 'personal_api_token'. Drives the reveal page's copy.",
    )


class OneTimeSecretRevealSerializer(serializers.Serializer):
    secret_type = serializers.CharField(
        help_text="The kind of secret revealed, e.g. 'personal_api_token'.",
    )
    value = serializers.CharField(
        help_text="The revealed secret value. Returned exactly once — the link is burned by this call.",
    )


class OneTimeSecretViewSet(viewsets.GenericViewSet):
    """Reveal a one-time secret to the logged-in human exactly once.

    Session auth only, by design: a personal API key or OAuth token can never reveal a secret, so an
    agent holding one cannot open the reveal URL — only the human's browser session can.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    lookup_field = "token"
    lookup_value_regex = "[^/]+"

    @extend_schema(responses={200: OneTimeSecretSerializer})
    def retrieve(self, request: Request, token: str | None = None, **kwargs) -> Response:
        """Peek at a one-time secret: returns its type and availability without consuming it."""
        user = cast(User, request.user)
        result = peek_one_time_secret(cast(str, token), user_id=user.id)
        if not result:
            raise NotFound(_UNAVAILABLE_MESSAGE)
        return Response(OneTimeSecretSerializer({"secret_type": result["type"]}).data)

    @extend_schema(request=None, responses={200: OneTimeSecretRevealSerializer})
    @action(detail=True, methods=["post"])
    def reveal(self, request: Request, token: str | None = None, **kwargs) -> Response:
        """Reveal the secret value exactly once, then burn the link."""
        user = cast(User, request.user)
        result = consume_one_time_secret(cast(str, token), user_id=user.id)
        if not result:
            raise NotFound(_UNAVAILABLE_MESSAGE)
        return Response(OneTimeSecretRevealSerializer({"secret_type": result["type"], "value": result["value"]}).data)
