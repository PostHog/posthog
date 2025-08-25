import base64
from hashlib import sha256
from typing import Any

from django.db.models import Q

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.models import Team
from posthog.models.personal_api_key import find_personal_api_key
from posthog.redis import get_client
from posthog.tasks.email import send_personal_api_key_exposed

GITHUB_KEYS_URI = "https://api.github.com/meta/public_keys/secret_scanning"
TWENTY_FOUR_HOURS = 60 * 60 * 24


class SignatureVerificationError(Exception):
    pass


def verify_github_signature(payload: str, kid: str, sig: str) -> None:
    redis_client = get_client()
    cache_key = f"github:public_key:{kid}"

    pem = redis_client.get(cache_key)
    if pem:
        pem = pem.decode("utf-8") if isinstance(pem, bytes) else pem

    if pem is None:
        try:
            resp = requests.get(GITHUB_KEYS_URI, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            raise SignatureVerificationError("Failed to fetch GitHub public keys")

        public_keys = data.get("public_keys")
        if not isinstance(public_keys, list) or not public_keys:
            raise SignatureVerificationError("No public keys found")

        entry = next((k for k in public_keys if k.get("key_identifier") == kid), None)
        if entry is None:
            raise SignatureVerificationError("No public key found matching key identifier")

        pem = entry.get("key")
        if not isinstance(pem, str) or not pem.strip():
            raise SignatureVerificationError("Malformed public key entry")

        redis_client.setex(cache_key, TWENTY_FOUR_HOURS, pem)

    try:
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as e:
        raise SignatureVerificationError("Unable to parse public key") from e

    if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name.lower() not in ("secp256r1", "prime256v1"):
        raise SignatureVerificationError("Unsupported public key type/curve (expected ECDSA P-256)")

    try:
        sig_bytes = base64.b64decode(sig, validate=True)
    except Exception as e:
        raise SignatureVerificationError("Signature is not valid base64") from e

    message = payload.encode("utf-8")

    try:
        pub.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise SignatureVerificationError("Signature does not match payload") from e


class SecretAlertSerializer(serializers.Serializer):
    token = serializers.CharField()
    type = serializers.ChoiceField(choices=["posthog_personal_api_key", "posthog_feature_flags_secure_api_key"])
    url = serializers.CharField(allow_blank=True)
    source: Any = serializers.CharField()


class SecretAlert(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def post(self, request):
        kid = (request.headers.get("Github-Public-Key-Identifier") or "").strip()
        sig = (request.headers.get("Github-Public-Key-Signature") or "").strip()

        if not kid:
            raise ValidationError(
                {
                    "headers": {
                        "Github-Public-Key-Identifier": "required non-blank string",
                    }
                }
            )
        if not sig:
            raise ValidationError(
                {
                    "headers": {
                        "Github-Public-Key-Signature": "required non-blank string",
                    }
                }
            )

        try:
            verify_github_signature(request.body.decode("utf-8"), kid, sig)
        except SignatureVerificationError:
            return Response({"detail": "Invalid signature"}, status=401)

        if not isinstance(request.data, list):
            raise ValidationError(detail="Expected a JSON array")
        if len(request.data) < 1:
            raise ValidationError(detail="Array must contain at least one item")

        secret_alert = SecretAlertSerializer(data=request.data, many=True)
        secret_alert.is_valid(raise_exception=True)
        items = secret_alert.validated_data

        results = []
        for item in items:
            result = {
                "token_hash": sha256(item["token"].encode("utf-8")).hexdigest(),
                "token_type": item["type"],
                "label": "false_positive",
            }

            if item["type"] == "posthog_personal_api_key":
                key_lookup = find_personal_api_key(item["token"])
                if key_lookup is not None:
                    result["label"] = "true_positive"
                    more_info = f"This key was detected by GitHub at {item['url']}."

                    # roll key
                    key, _ = key_lookup
                    old_mask_value = key.mask_value
                    serializer = PersonalAPIKeySerializer(instance=key)
                    serializer.roll(key)
                    send_personal_api_key_exposed(key.user.id, key.id, old_mask_value, more_info)

            elif item["type"] == "posthog_feature_flags_secure_api_key":
                try:
                    _ = Team.objects.get(Q(secret_api_token=item["token"]) | Q(secret_api_token_backup=item["token"]))
                    # TODO send email to team members
                    result["label"] = "true_positive"

                except Team.DoesNotExist:
                    pass

            else:
                raise ValidationError(detail="Unexpected alert type")

            results.append(result)

        return Response(results)
