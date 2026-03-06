from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from .signature import SUPPORTED_VERSIONS, verify_stripe_signature

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

    return Response(
        {
            "data": [
                {
                    "id": "posthog_analytics",
                    "description": "Product analytics, feature flags, session replay, and more",
                    "categories": ["analytics", "feature_flags", "observability"],
                    "pricing": {"type": "free"},
                }
            ],
            "next_cursor": "",
        }
    )
