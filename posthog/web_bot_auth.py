import json
import time
import base64
import hashlib
import secrets
from typing import Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CONTENT_TYPE = "application/http-message-signatures-directory+json"
_TAG = "http-message-signatures-directory"
_SIGNATURE_LIFETIME_SECONDS = 300

# Signed as a constant, never read from the request. The signature covers the authority, so a signer
# that signed whichever Host it was handed would give any site proxying this route a directory that
# verifies on that site while carrying our key. Preventing exactly that is what this signature is
# for. posthog.com reaches this route through a rewrite, so the Host here is not the public one.
_AUTHORITY = "posthog.com"


def _private_key() -> Optional[Ed25519PrivateKey]:
    pem = settings.WEB_BOT_AUTH_PRIVATE_KEY
    if not pem:
        return None
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("WEB_BOT_AUTH_PRIVATE_KEY is not an Ed25519 private key")
    return key


def public_jwk(key: Ed25519PrivateKey) -> dict[str, str]:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def jwk_thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638, over the required members only. RFC 8037 appendix A.3 fixes those for Ed25519."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).decode().rstrip("=")


def signature_base(keyid: str, nonce: str, created_at_seconds: int) -> tuple[str, str]:
    """
    RFC 9421 section 2.5. Returns the parameters alongside the base, because Signature-Input must
    repeat them byte for byte and building them twice invites the two copies to differ.
    """
    params = (
        f'("@authority";req);alg="ed25519";keyid="{keyid}";nonce="{nonce}";'
        f'tag="{_TAG}";created={created_at_seconds};expires={created_at_seconds + _SIGNATURE_LIFETIME_SECONDS}'
    )
    return params, f'"@authority";req: {_AUTHORITY}\n"@signature-params": {params}'


def signed_directory(key: Ed25519PrivateKey, created_at_seconds: int, nonce: str) -> tuple[str, dict[str, str]]:
    jwk = public_jwk(key)
    params, base = signature_base(jwk_thumbprint(jwk), nonce, created_at_seconds)
    signature = key.sign(base.encode())
    return (
        json.dumps({"keys": [jwk]}),
        {
            "Content-Type": CONTENT_TYPE,
            "Signature-Input": f"sig1={params}",
            "Signature": f"sig1=:{base64.b64encode(signature).decode()}:",
            # A cached copy outlives its own signature, so every reader must reach this view.
            "Cache-Control": "no-store",
        },
    )


def http_message_signatures_directory(request: HttpRequest) -> HttpResponse:
    """
    The Web Bot Auth key directory for PostHogSessionReplayBot, served at posthog.com through a
    rewrite. A stored file cannot serve this: Cloudflare uses a key only when the response carries a
    signature made with that key, covering the authority asked for and expiring minutes later.

    https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/
    """
    key = _private_key()
    if key is None:
        return HttpResponseNotFound()

    body, headers = signed_directory(key, int(time.time()), base64.b64encode(secrets.token_bytes(32)).decode())
    response = HttpResponse(body, content_type=CONTENT_TYPE)
    for name, value in headers.items():
        response[name] = value
    return response
