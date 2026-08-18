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

from posthog.cloud_utils import is_cloud_us

CONTENT_TYPE = "application/http-message-signatures-directory+json"
_TAG = "http-message-signatures-directory"
_SIGNATURE_LIFETIME_SECONDS = 300

# Signed as a constant, never read from the request. The signature covers the authority, so a signer
# that signed whichever Host it was handed would give any site proxying this route a directory that
# verifies on that site while carrying our key. Preventing exactly that is what this signature is for.
#
# This is the origin the bot names in Signature-Agent, and it is us.posthog.com rather than
# posthog.com because Vercel reserves /.well-known and will not rewrite it, so posthog.com cannot
# serve a response it computes per request.
_AUTHORITY = "us.posthog.com"


def _private_keys() -> list[Ed25519PrivateKey]:
    keys: list[Ed25519PrivateKey] = []
    for pem in settings.WEB_BOT_AUTH_PRIVATE_KEYS:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError("WEB_BOT_AUTH_PRIVATE_KEYS contains a key that is not Ed25519")
        keys.append(key)
    return keys


def public_jwk(key: Ed25519PrivateKey) -> dict[str, str]:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).decode().rstrip("=")}


def jwk_thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638, over the required members only. RFC 8037 appendix A.3 fixes those for Ed25519."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).decode().rstrip("=")


def signature_base(keyid: str, nonce: str, created_at_seconds: int, content_digest: str) -> tuple[str, str]:
    """
    RFC 9421 section 2.5. Returns the parameters alongside the base, because Signature-Input must
    repeat them byte for byte and building them twice invites the two copies to differ.
    """
    params = (
        f'("@authority";req "content-digest");alg="ed25519";keyid="{keyid}";nonce="{nonce}";'
        f'tag="{_TAG}";created={created_at_seconds};expires={created_at_seconds + _SIGNATURE_LIFETIME_SECONDS}'
    )
    return (
        params,
        f'"@authority";req: {_AUTHORITY}\n"content-digest": {content_digest}\n"@signature-params": {params}',
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
        params, base = signature_base(jwk_thumbprint(jwk), nonce, created_at_seconds, content_digest)
        signature_inputs.append(f"{label}={params}")
        signatures.append(f"{label}=:{base64.b64encode(key.sign(base.encode())).decode()}:")
    return (
        body,
        {
            "Content-Type": CONTENT_TYPE,
            "Content-Digest": content_digest,
            "Signature-Input": ", ".join(signature_inputs),
            "Signature": ", ".join(signatures),
            # A cached copy outlives its own signature, so every reader must reach this view.
            "Cache-Control": "no-store",
        },
    )


def http_message_signatures_directory(request: HttpRequest) -> HttpResponse:
    """
    The Web Bot Auth key directory for PostHogSessionReplayBot. A stored file cannot serve this:
    Cloudflare uses a key only when the response carries a signature made with that key, covering
    the authority asked for and expiring minutes later.

    https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/
    """
    # The signature covers _AUTHORITY, so anywhere else would serve a directory that cannot verify
    # where it is served. The keys are deployed to every region, so their presence does not gate this.
    if not is_cloud_us():
        return HttpResponseNotFound()

    keys = _private_keys()
    if not keys:
        return HttpResponseNotFound()

    body, headers = signed_directory(keys, int(time.time()), base64.b64encode(secrets.token_bytes(32)).decode())
    response = HttpResponse(body, content_type=CONTENT_TYPE)
    for name, value in headers.items():
        response[name] = value
    return response
