import json
import base64

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from temporalio.api.common.v1 import Payload

from posthog.temporal.common.codec import EncryptionCodec


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def decode_payloads(request):
    """Decode encrypted Temporal payloads for the Temporal UI.

    This endpoint is used by the Temporal UI to decrypt workflow metadata
    when viewing workflow executions.
    """
    cors_origin = "https://temporal-ui.posthog.orb.local"

    # CORS preflight
    if request.method == "OPTIONS":
        response = JsonResponse({})
        response["Access-Control-Allow-Origin"] = cors_origin
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, X-Namespace, Authorization, x-namespace"
        return response

    try:
        body = json.loads(request.body)
        payloads = body.get("payloads", [])

        if not payloads:
            response = JsonResponse({"payloads": []})
            response["Access-Control-Allow-Origin"] = cors_origin
            return response

        codec = EncryptionCodec(settings)
        decoded_payloads = []

        for payload_data in payloads:
            # Decode encoded (base64) fields from the request
            metadata = {}
            if payload_data.get("metadata"):
                for k, v in payload_data["metadata"].items():
                    if isinstance(v, str):
                        try:
                            metadata[k] = base64.b64decode(v)
                        except Exception:
                            # Invalid base64 encoding
                            raise ValueError("Invalid base64 encoding")
                    else:
                        pass

            # Decode the data field from base64
            data = payload_data.get("data", "")
            if isinstance(data, str) and data:
                data = base64.b64decode(data)
            elif not data:
                data = b""

            # Check if this payload is encrypted with our EncryptionCodec
            if metadata.get("encoding", b"") == b"binary/encrypted":
                try:
                    # Decrypt the payload data
                    decrypted_data = codec.decrypt(data)
                    # Parse the decrypted payload
                    decrypted_payload = Payload.FromString(decrypted_data)

                    # Prepare response with base64 encoded fields
                    response_metadata = {}
                    if decrypted_payload.metadata:
                        for key, value in decrypted_payload.metadata.items():
                            if isinstance(value, bytes):
                                response_metadata[key] = base64.b64encode(value).decode("utf-8")
                            else:
                                response_metadata[key] = str(value)

                    decoded_payloads.append(
                        {
                            "metadata": response_metadata,
                            "data": base64.b64encode(decrypted_payload.data).decode("utf-8")
                            if decrypted_payload.data
                            else "",
                        }
                    )
                except Exception:
                    # If decryption fails, return the original payload
                    decoded_payloads.append(payload_data)

        response = JsonResponse({"payloads": decoded_payloads})
        response["Access-Control-Allow-Origin"] = cors_origin
        return response

    except json.JSONDecodeError:
        response = JsonResponse({"error": "Invalid JSON"}, status=400)
        response["Access-Control-Allow-Origin"] = cors_origin
        return response
    except Exception as e:
        response = JsonResponse({"error": str(e)}, status=500)
        response["Access-Control-Allow-Origin"] = cors_origin
        return response
