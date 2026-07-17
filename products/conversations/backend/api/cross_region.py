"""Receiver for cross-region org-membership verification probes.

The sibling region calls this over an HMAC-signed body (see
``products/conversations/backend/cross_region.py``); this endpoint answers which
of the supplied identities have a verified ``OrganizationMembership`` in the
local region. It performs no proxying of its own, so there is no risk of a probe
loop between regions.
"""

from typing import Any

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import WebhookSignatureAuthentication

from products.conversations.backend.cross_region import (
    CROSS_REGION_SIGNATURE_HEADER,
    CROSS_REGION_TIMESTAMP_HEADER,
    OrgIdentity,
    verify_org_memberships,
)


class CrossRegionOrgVerificationAuthentication(WebhookSignatureAuthentication):
    """HMAC verification for cross-region org-membership probes.

    The base class fails closed on missing headers, an unset secret, a stale
    timestamp, or a digest mismatch. There is no authenticated user — the request
    is a trusted server-to-server call proven by the shared secret.
    """

    def get_signature_header(self) -> str:
        return CROSS_REGION_SIGNATURE_HEADER

    def get_timestamp_header(self) -> str:
        return CROSS_REGION_TIMESTAMP_HEADER

    def build_hmac_input(self, timestamp: str, body: str) -> str:
        return f"v0:{timestamp}:{body}"

    def get_signing_secret(self, request: Request) -> str | None:
        return settings.CONVERSATIONS_CROSS_REGION_SECRET or None

    def authenticate(self, request: Request) -> tuple[AnonymousUser, Any] | None:
        try:
            return super().authenticate(request)
        except UnicodeDecodeError:
            # The base class decodes the raw body before verifying; garbage bytes
            # are an auth failure, not a 500.
            raise exceptions.AuthenticationFailed("Invalid request body encoding.")


class CrossRegionOrgVerificationViewSet(viewsets.ViewSet):
    """Local-region membership check for the sibling region's enrichment run.

    The signed body carries the identities to check; the response lists the input
    indices that verify. Trust comes entirely from the HMAC signature, so there is
    no user, permission, or throttle layer.
    """

    authentication_classes = [CrossRegionOrgVerificationAuthentication]
    permission_classes = []
    throttle_classes = []

    @extend_schema(exclude=True)
    def create(self, request: Request) -> Response:
        raw_identities = request.data.get("identities")
        if not isinstance(raw_identities, list):
            return Response({"detail": "identities must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        identities: list[OrgIdentity] = []
        for item in raw_identities:
            if not isinstance(item, dict):
                return Response({"detail": "each identity must be an object"}, status=status.HTTP_400_BAD_REQUEST)
            organization_id = item.get("organization_id")
            if not isinstance(organization_id, str) or not organization_id:
                return Response({"detail": "organization_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            distinct_id = item.get("distinct_id") or ""
            email_from = item.get("email_from") or ""
            identities.append(OrgIdentity(organization_id, str(distinct_id), str(email_from)))

        verified = verify_org_memberships(identities)
        verified_indices = [index for index, identity in enumerate(identities) if identity in verified]
        return Response({"verified_indices": verified_indices})
