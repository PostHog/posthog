from hashlib import sha256

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.secret_revocation import (
    CANONICAL_OAUTH_ACCESS_TOKEN,
    CANONICAL_OAUTH_REFRESH_TOKEN,
    CANONICAL_PERSONAL_API_KEY,
    CANONICAL_PROJECT_SECRET_API_KEY,
    revoke_leaked_secret,
)
from posthog.rate_limit import LeakedKeyReportThrottle

PUBLIC_REPORT_MORE_INFO = "This key was reported as leaked via PostHog's public key-revocation API."


class LeakedKeyReportSerializer(serializers.Serializer):
    token = serializers.CharField(
        help_text="The leaked PostHog personal API key, project secret API key, or OAuth access/refresh token to revoke.",
    )


class LeakedKeyReportResponseSerializer(serializers.Serializer):
    found = serializers.BooleanField(
        help_text="Whether a matching PostHog key or token was found and revoked.",
    )
    type = serializers.ChoiceField(
        choices=[
            CANONICAL_PERSONAL_API_KEY,
            CANONICAL_PROJECT_SECRET_API_KEY,
            CANONICAL_OAUTH_ACCESS_TOKEN,
            CANONICAL_OAUTH_REFRESH_TOKEN,
        ],
        allow_null=True,
        help_text="The type of key that was found and revoked, or null if no match was found.",
    )


class PublicLeakedKeyReport(APIView):
    """
    Public, unauthenticated self-service endpoint: submit a leaked PostHog token and,
    if it's live, it's revoked immediately and the owner is notified. Safety relies on
    possession of the plaintext token, not a signature — see secret_revocation.py.

    Region-local only, no cross-region relay: a "found": false result does not rule
    out the token being live in the other region. See the endpoint description below.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LeakedKeyReportThrottle]

    @validated_request(
        request_serializer=LeakedKeyReportSerializer,
        responses={
            200: OpenApiResponse(response=LeakedKeyReportResponseSerializer, description="Lookup result."),
            400: OpenApiResponse(description="Missing or blank token."),
            429: OpenApiResponse(description="Too many requests from this IP."),
        },
        summary="Report and revoke a leaked PostHog API key or token",
        description=(
            "Public, unauthenticated endpoint for self-service revocation of a leaked PostHog "
            "personal API key, project secret API key, or OAuth access/refresh token. If the "
            "token is live it is revoked immediately and the owner is notified by email.\n\n"
            'This endpoint only checks the region it is running on. `"found": false` does not '
            "guarantee the token is safe — if you're not sure which region issued it, also try "
            "the other region's endpoint: https://app.posthog.com/api/alerts/leaked_key or "
            "https://eu.posthog.com/api/alerts/leaked_key."
        ),
        extensions={"x-product": "core"},
    )
    def post(self, request: ValidatedRequest) -> Response:
        token = request.validated_data["token"]

        result = revoke_leaked_secret(token, key_type=None, more_info=PUBLIC_REPORT_MORE_INFO)

        # Unlike github_secret_alert, no token_prefix/token_suffix here: GitHub already
        # confirmed the string is a real PostHog-shaped secret before that event fires,
        # but this endpoint's callers are the whole internet, and people will paste
        # things that aren't PostHog keys at all. token_sha256 alone is enough for
        # dedup/monitoring without persisting fragments of third-party secrets.
        posthoganalytics.capture(
            distinct_id=None,
            event="public_leaked_key_report",
            properties={
                "found": result.found,
                "type": result.key_type,
                "token_length": len(token),
                "token_sha256": sha256(token.encode("utf-8")).hexdigest(),
            },
        )

        return Response({"found": result.found, "type": result.key_type})
