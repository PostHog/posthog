import base64
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.db.models import Q

import requests
import structlog
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
from posthog.models.utils import mask_key_value
from posthog.redis import get_client
from posthog.tasks.email import send_personal_api_key_exposed, send_project_secret_api_key_exposed
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

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


def relay_to_eu(raw_body: str, kid: str, sig: str) -> list[dict] | None:
    """Relay request to EU. Returns EU results or None on failure."""
    # Prevent infinite loop if someone accidentally configures relay URL in EU
    if get_instance_region() == "EU":
        return None

    url = settings.GITHUB_SECRET_ALERT_RELAY_URL
    if not url:
        return None
    try:
        resp = requests.post(
            url,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "Github-Public-Key-Identifier": kid,
                "Github-Public-Key-Signature": sig,
            },
            # GitHub expects a response w/in 30 seconds, so EU gets half that
            timeout=15,
        )
        resp.raise_for_status()
        posthoganalytics.capture(
            distinct_id=None,
            event="github_secret_alert_relay_success",
        )
        return resp.json()
    except Exception as e:
        logger.warning("Failed to relay GitHub secret alert to EU", error=str(e))
        posthoganalytics.capture(
            distinct_id=None,
            event="github_secret_alert_relay_failure",
            properties={"error": str(e)},
        )
        return None


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
        pending_events = []
        for item in items:
            # Strip whitespace from token in case GitHub sends it with extra formatting
            token = item["token"].strip()
            token_sha256 = sha256(token.encode("utf-8")).hexdigest()

            result = {
                "token_hash": token_sha256,
                "token_type": item["type"],
                "label": "false_positive",
            }

            # Debug info for monitoring token lookups
            token_debug = {
                "token_length": len(token),
                "token_prefix": token[:8],
                "token_suffix": token[-4:],
                "token_sha256": token_sha256,
            }

            local_found = False

            if item["type"] == GITHUB_TYPE_FOR_PERSONAL_API_KEY:
                key_lookup = find_personal_api_key(token)
                local_found = key_lookup is not None

                pending_events.append(
                    {
                        "type": "personal_api_key",
                        "source": item["source"],
                        "url": item["url"],
                        "found": local_found,
                        "token_hash": token_sha256,
                        **token_debug,
                    }
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
                try:
                    team = Team.objects.get(Q(secret_api_token=token) | Q(secret_api_token_backup=token))
                    local_found = True
                    result["label"] = "true_positive"

                    PROJECT_SECRET_API_KEY_LEAKED_COUNTER.inc()

                    more_info = f"This key was detected by GitHub at {item['url']}."
                    send_project_secret_api_key_exposed(team.id, mask_key_value(token), more_info)

                except Team.DoesNotExist:
                    pass

                pending_events.append(
                    {
                        "type": "project_secret_api_key",
                        "source": item["source"],
                        "url": item["url"],
                        "found": local_found,
                        "token_hash": token_sha256,
                        **token_debug,
                    }
                )

            else:
                raise ValidationError(detail="Unexpected alert type")

            results.append(result)

        # GitHub's secret scanning program only supports a single webhook endpoint, so we
        # receive all alerts in US and relay to EU synchronously when needed. We only relay
        # false positives (keys not found locally) since true positives are already handled.
        # This must complete within GitHub's 30-second timeout, hence EU gets 15s.
        eu_found_hashes: set[str] = set()
        has_false_positives = any(r["label"] == "false_positive" for r in results)
        if has_false_positives:
            eu_results = relay_to_eu(raw_body, kid, sig)
            if eu_results:
                eu_by_hash = {r["token_hash"]: r for r in eu_results}
                for r in results:
                    eu_r = eu_by_hash.get(r["token_hash"])
                    if eu_r and eu_r["label"] == "true_positive":
                        r["label"] = "true_positive"
                        eu_found_hashes.add(r["token_hash"])

        # Capture events with correct key_found_region.
        # Don't capture events from the EU, otherwise we'll double count events (US and EU)
        if get_instance_region() != "EU":
            for event_data in pending_events:
                token_hash = event_data.pop("token_hash")

                if token_hash in eu_found_hashes:
                    event_data["key_found_region"] = "EU"
                    event_data["found"] = True
                elif event_data["found"]:
                    event_data["key_found_region"] = get_instance_region()

                posthoganalytics.capture(
                    distinct_id=None,
                    event="github_secret_alert",
                    properties=event_data,
                )

        return Response(results)
