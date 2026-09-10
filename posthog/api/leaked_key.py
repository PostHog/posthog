from hashlib import sha256

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.parsers import JSONParser
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
from posthog.utils import get_instance_region

PUBLIC_REPORT_MORE_INFO = "This key was reported as leaked via PostHog's public key-revocation API."


class LeakedKeyReportSerializer(serializers.Serializer):
    token = serializers.CharField(
        # The longest key we issue is 51 characters. The cap rejects an oversized body
        # before any hashing or lookup work happens.
        max_length=200,
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
    if it matches a real credential, it's revoked immediately and the owner is
    notified — even if the submitted OAuth access token has itself already expired,
    since the paired refresh token it protects may still be live. Safety relies on
    possession of the plaintext token, not a signature — see secret_revocation.py.

    Region-local only, no cross-region relay: a "found": false result does not rule
    out the token being live in the other region. See the endpoint description below.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LeakedKeyReportThrottle]
    parser_classes = [JSONParser]

    # No scope_object: this endpoint is intentionally public and unscoped, not tied to
    # a team/org resource, so APIScopePermission's scope model doesn't apply here. It
    # opts into the public API docs directly instead.
    include_in_api_docs = True

    @validated_request(
        request_serializer=LeakedKeyReportSerializer,
        responses={
            200: OpenApiResponse(response=LeakedKeyReportResponseSerializer, description="Lookup result."),
            400: OpenApiResponse(description="The token is missing, blank, or longer than 200 characters."),
            429: OpenApiResponse(description="Too many requests from this IP."),
        },
        summary="Report and revoke a leaked PostHog API key or token",
        description=(
            "Public, unauthenticated endpoint for self-service revocation of a leaked PostHog "
            "personal API key, project secret API key, or OAuth access/refresh token. If the "
            "token matches a real credential, it is revoked immediately and the owner is "
            "notified by email. This includes an expired OAuth access token: the paired "
            "refresh token it protects may still be live.\n\n"
            'This endpoint only checks the region it is running on. `"found": false` does not '
            "guarantee the token is safe. If you're not sure which region issued it, check "
            "both: https://app.posthog.com/api/revoke_leaked_key and "
            "https://eu.posthog.com/api/revoke_leaked_key."
        ),
        extensions={"x-product": "core"},
    )
    def post(self, request: ValidatedRequest) -> Response:
        token = request.validated_data["token"]

        result = revoke_leaked_secret(token, key_type=None, more_info=PUBLIC_REPORT_MORE_INFO)

        # Unlike github_secret_alert, no token_prefix/token_suffix here: GitHub already
        # confirmed the string is a real PostHog-shaped secret before that event fires,
        # but this endpoint's callers are the whole internet, and people will paste
        # things that aren't PostHog keys at all.
        properties: dict[str, str | int | bool | None] = {
            "found": result.found,
            "type": result.key_type,
            "token_length": len(token),
            # With no cross-region relay, this is the only signal showing whether
            # callers in one region are reporting keys the other region issued.
            "region": get_instance_region(),
        }
        if result.found:
            # Only hash a token once it matched a real PostHog credential: those are
            # high-entropy and this hash isn't practically reversible. For the common
            # case of a caller pasting something that isn't a PostHog secret at all, an
            # unsalted SHA-256 of a low-entropy string (a password, a short token) is
            # dictionary/rainbow-table reversible, so we don't persist a recoverable
            # copy of a third party's actual secret.
            properties["token_sha256"] = sha256(token.encode("utf-8")).hexdigest()
        posthoganalytics.capture(
            distinct_id=None,
            event="public_leaked_key_report",
            properties=properties,
        )

        return Response({"found": result.found, "type": result.key_type})
