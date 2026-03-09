from __future__ import annotations

from typing import Any

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from .signature import SUPPORTED_VERSIONS, verify_stripe_signature

# ---------------------------------------------------------------------------
# Service catalog — a single "posthog" service. PostHog projects include all
# products (analytics, session replay, feature flags, etc.) so there's one
# provisionable service. PostHog handles billing itself (payment_credentials:
# "provider"), so pricing is "free" from Stripe's perspective.
# ---------------------------------------------------------------------------

POSTHOG_SERVICE_ID = "posthog"

POSTHOG_SERVICE: dict[str, Any] = {
    "id": POSTHOG_SERVICE_ID,
    "description": "PostHog — product analytics, session replay, feature flags, A/B testing, surveys, and more",
    "categories": ["analytics", "observability", "feature_flags", "ai"],
    "pricing": {
        "type": "free",
    },
}


def _get_services() -> list[dict[str, Any]]:
    return [POSTHOG_SERVICE]


# ---------------------------------------------------------------------------
# GET /provisioning/health
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_health(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error

    return Response({"supported_versions": SUPPORTED_VERSIONS, "status": "ok"})


# ---------------------------------------------------------------------------
# GET /provisioning/services
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_services(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error

    return Response({"data": _get_services(), "next_cursor": ""})
