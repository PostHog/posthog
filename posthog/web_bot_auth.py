import json
import time
import base64
import hashlib
import secrets
from collections.abc import Sequence

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from posthog.dataclasses import frozen
from posthog.web_bot_auth_keys import load_web_bot_auth_private_key_configuration

CONTENT_TYPE = "application/http-message-signatures-directory+json"
_TAG = "http-message-signatures-directory"
_SIGNATURE_LIFETIME_SECONDS = 300
_CACHE_MAX_AGE_SECONDS = 60

# Covering @authority prevents cross-authority signature replay. Keep its value constant so this
# endpoint cannot act as a confused deputy and sign a directory for a requester-controlled domain.
# Otherwise, another site could proxy this route and receive a directory that verifies for its
# domain but contains our public key.
#
# PostHog normally hosts public identity metadata on the root posthog.com domain. Web Bot Auth is an
# exception because its directory response needs a cryptographic signature with creation and
# expiration timestamps. The root domain runs on Vercel, which only serves static files under
# /.well-known, so Signature-Agent points to this Django app at us.posthog.com.
_AUTHORITY = "us.posthog.com"


@frozen
class SignatureBase:
    parameters: str
    value: str


def public_jwk(key: Ed25519PrivateKey) -> dict[str, str]:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def jwk_thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638 requires only these members. RFC 8037, appendix A.3, defines them for Ed25519."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).decode().rstrip("=")


def signature_base(keyid: str, nonce: str, created_at_seconds: int, content_digest: str) -> SignatureBase:
    """
    RFC 9421 section 2.5 defines this signature base. Signature-Input must repeat the parameter bytes,
    so this function returns the parameters with the base.
    """
    params = (
        f'("@authority";req "content-digest");alg="ed25519";keyid="{keyid}";nonce="{nonce}";'
        f'tag="{_TAG}";created={created_at_seconds};expires={created_at_seconds + _SIGNATURE_LIFETIME_SECONDS}'
    )
    return SignatureBase(
        parameters=params,
        value=f'"@authority";req: {_AUTHORITY}\n"content-digest": {content_digest}\n"@signature-params": {params}',
    )


def signed_directory(
    keys: Sequence[Ed25519PrivateKey], created_at_seconds: int, nonce: str
) -> tuple[str, dict[str, str]]:
    jwks = [public_jwk(key) for key in keys]
    body = json.dumps({"keys": jwks})
    content_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}:"
    signature_inputs: list[str] = []
    signatures: list[str] = []
    for index, (key, jwk) in enumerate(zip(keys, jwks, strict=True), start=1):
        label = f"sig{index}"
        signature_base_value = signature_base(jwk_thumbprint(jwk), nonce, created_at_seconds, content_digest)
        signature_inputs.append(f"{label}={signature_base_value.parameters}")
        signatures.append(f"{label}=:{base64.b64encode(key.sign(signature_base_value.value.encode())).decode()}:")
    return (
        body,
        {
            "Content-Type": CONTENT_TYPE,
            "Content-Digest": content_digest,
            "Signature-Input": ", ".join(signature_inputs),
            "Signature": ", ".join(signatures),
            "Cache-Control": f"public, max-age={_CACHE_MAX_AGE_SECONDS}",
        },
    )


def http_message_signatures_directory(request: HttpRequest) -> HttpResponse:
    """
    Cloudflare uses the PostHogImageFetcherBot public key only if the corresponding private key signs
    this directory response. The signature covers the requested authority and expires after five minutes.

    https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/
    """
    # The signature covers _AUTHORITY, so only the US deployment can serve this directory.
    if (settings.CLOUD_DEPLOYMENT or "").upper() != "US":
        return HttpResponseNotFound()

    try:
        configuration = load_web_bot_auth_private_key_configuration(
            tuple(settings.WEB_BOT_AUTH_PRIVATE_KEYS),
            require_at_least_one=settings.WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT,
        )
    except Exception:
        return HttpResponse(status=503)
    if configuration.validation_error is not None:
        return HttpResponse(status=503)
    if not configuration.private_keys:
        return HttpResponseNotFound()

    body, headers = signed_directory(
        configuration.private_keys,
        int(time.time()),
        base64.b64encode(secrets.token_bytes(32)).decode(),
    )
    response = HttpResponse(body, content_type=CONTENT_TYPE)
    for name, value in headers.items():
        response[name] = value
    return response
