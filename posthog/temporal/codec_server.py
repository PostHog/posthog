from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from asgiref.sync import async_to_sync
from google.protobuf import json_format
from temporalio.api.common.v1 import Payloads

from posthog.temporal.common.codec import EncryptionCodec


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def decode_payloads(request):
    """Decode encrypted Temporal payloads for the Temporal UI.

    This endpoint is used by the Temporal UI to decrypt workflow metadata
    when viewing workflow executions.
    """

    allowed_origins = ["https://temporal-ui.posthog.orb.local", "http://localhost:8081"]
    request_origin = request.headers.get("Origin")

    # CORS preflight
    if request.method == "OPTIONS":
        response = HttpResponse()
        if request_origin in allowed_origins:
            response["Access-Control-Allow-Origin"] = request_origin
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-Namespace, Authorization"
        return response

    if request_origin not in allowed_origins:
        return JsonResponse({"error": "CORS not allowed"}, status=403)

    try:
        payloads = json_format.Parse(request.body, Payloads())
        codec = EncryptionCodec(settings)

        decoded_list = async_to_sync(codec.decode)(payloads.payloads)

        response_payloads = Payloads(payloads=decoded_list)

        response = HttpResponse(json_format.MessageToJson(response_payloads), content_type="application/json")
        response["Access-Control-Allow-Origin"] = request_origin
        return response

    except Exception:
        response = JsonResponse({"Internal Server Error"}, status=500)
        if request_origin in allowed_origins:
            response["Access-Control-Allow-Origin"] = request_origin
        return response
