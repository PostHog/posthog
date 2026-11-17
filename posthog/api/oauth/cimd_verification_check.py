"""Lets a region that does not issue CIMD verification tokens confirm one with the region that does.

Tokens are issued in PostHog US only, because one metadata document serves every region and carries one
token. EU sends the token it read from a partner's document, with the document's URL, and gets back whether
that token is valid there. Both values are already public in the document, so the endpoint answers anyone,
and it says nothing beyond yes or no.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.oauth.cimd import _token_is_bound_to_url
from posthog.models.oauth import find_cimd_verification_token
from posthog.rate_limit import IPThrottle

# Room for EU's refreshes of every partner document, which all come from a few addresses.
VERIFICATION_CHECK_RATE = "300/minute"


class CIMDVerificationCheckThrottle(IPThrottle):
    scope = "cimd_verification_check"
    rate = VERIFICATION_CHECK_RATE


class CIMDVerificationCheckRequestSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256, help_text="The phvt_ token published in the metadata document.")
    cimd_url = serializers.CharField(max_length=2048, help_text="The URL of the metadata document the token is in.")


class CIMDVerificationCheckView(APIView):
    permission_classes: list = []
    authentication_classes: list = []
    throttle_classes = [CIMDVerificationCheckThrottle]

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = CIMDVerificationCheckRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = find_cimd_verification_token(serializer.validated_data["token"])
        valid = token is not None and _token_is_bound_to_url(token, serializer.validated_data["cimd_url"])
        return Response({"valid": valid})
