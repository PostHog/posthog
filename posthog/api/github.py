import base64
from hashlib import sha256
from typing import Any

from django.db.models import Q

import requests
import posthoganalytics
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from prometheus_client import Counter
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

PERSONAL_API_KEY_LEAKED_COUNTER = Counter(
    "github_secrets_scanning_personal_api_key_leaked",
    "Number of valid Personal API Keys identified by GitHub secrets scanning",
)
PROJECT_SECRET_API_KEY_LEAKED_COUNTER = Counter(
    "github_secrets_scanning_project_secret_api_key_leaked",
    "Number of valid Project Secret API Keys identified by GitHub secrets scanning",
)

# GitHub sends swapped type names - these constants clarify the mismatch
GITHUB_TYPE_FOR_PERSONAL_API_KEY = "posthog_feature_flags_secure_api_key"
GITHUB_TYPE_FOR_PROJECT_SECRET = "posthog_personal_api_key"


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
    type = serializers.ChoiceField(choices=[GITHUB_TYPE_FOR_PERSONAL_API_KEY, GITHUB_TYPE_FOR_PROJECT_SECRET])
    url = serializers.CharField(allow_blank=True)
    source: Any = serializers.CharField()


class SecretAlert(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    def initialize_request(self, request, *args, **kwargs):
        """
        Store the raw body before DRF parses it.
        This is called before the parsers consume the body.
        """
        # Store raw body for signature verification
        request._raw_body = request.body
        return super().initialize_request(request, *args, **kwargs)

    def post(self, request):
        # Get the raw body we stored earlier
        try:
            raw_body = request._raw_body.decode("utf-8")
        except Exception:
            raise ValidationError(detail="Unable to read request body")

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
            verify_github_signature(raw_body, kid, sig)
        except SignatureVerificationError:
            posthoganalytics.capture(
                distinct_id=None,
                event="github_secret_alert_invalid_signature",
                properties={
                    "kid": kid,
                    "sig": sig,
                },
            )
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
            # Strip whitespace from token in case GitHub sends it with extra formatting
            token = item["token"].strip()

            result = {
                "token_hash": sha256(token.encode("utf-8")).hexdigest(),
                "token_type": item["type"],
                "label": "false_positive",
            }

            # Debug info for monitoring token lookups
            token_debug = {
                "token_length": len(token),
                "token_prefix": token[:8],
                "token_suffix": token[-4:],
            }

            if item["type"] == GITHUB_TYPE_FOR_PERSONAL_API_KEY:
                key_lookup = find_personal_api_key(token)
                posthoganalytics.capture(
                    distinct_id=None,
                    event="github_secret_alert",
                    properties={
                        "type": "personal_api_key",
                        "source": item["source"],
                        "url": item["url"],
                        "found": key_lookup is not None,
                        **token_debug,
                    },
                )

                if key_lookup is not None:
                    result["label"] = "true_positive"
                    more_info = f"This key was detected by GitHub at {item['url']}."

                    # roll key
                    key, _ = key_lookup
                    old_mask_value = key.mask_value

                    PERSONAL_API_KEY_LEAKED_COUNTER.inc()

                    serializer = PersonalAPIKeySerializer(instance=key)
                    serializer.roll(key)
                    send_personal_api_key_exposed(key.user.id, key.id, old_mask_value, more_info)

            elif item["type"] == GITHUB_TYPE_FOR_PROJECT_SECRET:
                found = False
                try:
                    _ = Team.objects.get(Q(secret_api_token=token) | Q(secret_api_token_backup=token))
                    found = True
                    # TODO send email to team members
                    result["label"] = "true_positive"

                    PROJECT_SECRET_API_KEY_LEAKED_COUNTER.inc()

                except Team.DoesNotExist:
                    pass

                posthoganalytics.capture(
                    distinct_id=None,
                    event="github_secret_alert",
                    properties={
                        "type": "project_secret_api_key",
                        "source": item["source"],
                        "url": item["url"],
                        "found": found,
                        **token_debug,
                    },
                )

            else:
                raise ValidationError(detail="Unexpected alert type")

            results.append(result)

        return Response(results)
