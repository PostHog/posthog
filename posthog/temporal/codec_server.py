import os
import hmac

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import structlog
from asgiref.sync import async_to_sync
from google.protobuf import json_format
from temporalio.api.common.v1 import Payloads

from posthog.temporal.common.codec import EncryptionCodec

logger = structlog.get_logger()


def _verify_authorization(request):
    """Verify the authorization header for codec server access.

    If not locally, a TEMPORAL_CODEC_AUTH_TOKEN environment variable must be set.

    Returns True if authorized, False otherwise.
    """
    expected_token = os.environ.get("TEMPORAL_CODEC_AUTH_TOKEN")

    # If no token is configured, check if we're in DEBUG mode
    if not expected_token:
        if settings.DEBUG:
            logger.warning(
                "TEMPORAL_CODEC_AUTH_TOKEN not set, allowing access in DEBUG mode, consider setting it for PRODUCTION!"
            )
            return True
        return False

    auth_header = request.headers.get("Authorization", "")

    # Parse Bearer token
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False

    provided_token = parts[1].strip()

    if not provided_token:
        return False

    return hmac.compare_digest(provided_token, expected_token)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def decode_payloads(request):
    """Decode encrypted Temporal payloads for the Temporal UI.

    This endpoint is used by the Temporal UI to decrypt workflow metadata
    when viewing workflow executions. Access is restricted via bearer token
    authentication for security.
    """

    allowed_origins = ["https://temporal-ui.posthog.orb.local", "http://localhost:8081"]
    request_origin = request.headers.get("Origin")

    if request_origin not in allowed_origins:
        return JsonResponse({"error": "CORS not allowed"}, status=403)

    # CORS preflight
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = request_origin
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, X-Namespace, Authorization"
        return response

    if not _verify_authorization(request):
        response = JsonResponse({"error": "Unauthorized"}, status=401)
        if request_origin in allowed_origins:
            response["Access-Control-Allow-Origin"] = request_origin
        return response

    try:
        payloads = json_format.Parse(request.body, Payloads())
        codec = EncryptionCodec(settings)

        decoded_list = async_to_sync(codec.decode)(payloads.payloads)

        response_payloads = Payloads(payloads=decoded_list)

        response = HttpResponse(json_format.MessageToJson(response_payloads), content_type="application/json")
        response["Access-Control-Allow-Origin"] = request_origin
        return response

    except Exception:
        logger.exception("Error decoding payloads via codec server")
        response = JsonResponse({"error": "Internal Server Error"}, status=500)
        if request_origin in allowed_origins:
            response["Access-Control-Allow-Origin"] = request_origin
        return response
