import ssl
import hmac
import json
import time
import base64
import hashlib
import secrets
import binascii
from typing import Final
from urllib.parse import urlsplit

import httpx
from rest_framework.exceptions import ValidationError

from posthog.security.pinned_httpx import pinned_client
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import validate_url_and_pin_ips

from products.cdp.backend.facade.mcp_event_types import MCPCallbackError

MCP_EVENT_NAME: Final = "posthog.event_captured"
MCP_EVENT_MAX_BYTES: Final = 256 * 1024
MCP_CREDENTIAL_INPUT: Final = "mcp_credential"


def signing_key(secret: str) -> bytes:
    if not secret.startswith("whsec_"):
        raise ValidationError({"secret": "Use a whsec_ signing secret supplied by the receiving client."})
    try:
        key = base64.b64decode(secret[6:], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValidationError({"secret": "The signing secret must contain valid base64."}) from error
    if not 24 <= len(key) <= 64:
        raise ValidationError({"secret": "The signing secret must decode to 24 to 64 bytes."})
    return key


def validate_callback_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ValidationError({"url": "Use an HTTPS callback URL without credentials or a fragment."}) from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValidationError({"url": "Use an HTTPS callback URL without credentials or a fragment."})
    return url


def signed_headers(
    *, subscription_id: str, webhook_id: str, body: str, secret: str, signed_at: int | None = None
) -> dict[str, str]:
    timestamp = str(signed_at if signed_at is not None else int(time.time()))
    signature = base64.b64encode(
        hmac.new(signing_key(secret), f"{webhook_id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "Content-Type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{signature}",
        "X-MCP-Subscription-Id": subscription_id,
    }


def verify_callback(*, subscription_id: str, url: str, secret: str) -> None:
    validate_callback_url(url)
    challenge = secrets.token_urlsafe(32)
    body = json.dumps({"type": "verification", "challenge": challenge}, separators=(",", ":"))
    headers = signed_headers(
        subscription_id=subscription_id, webhook_id=secrets.token_hex(16), body=body, secret=secret
    )
    try:
        verdict = validate_url_and_pin_ips(url)
        if not verdict.allowed:
            raise SSRFBlockedError
        with pinned_client(
            url, verdict.pinned_ips, total_timeout=10, max_response_bytes=8192, timeout=10, follow_redirects=False
        ) as client:
            response = client.post(url, content=body, headers=headers)
            if not 200 <= response.status_code < 300:
                raise MCPCallbackError("http_4xx" if response.status_code < 500 else "http_5xx")
            result = response.json()
            echoed = result.get("challenge") if isinstance(result, dict) else None
            if not isinstance(echoed, str) or not hmac.compare_digest(echoed.encode(), challenge.encode()):
                raise MCPCallbackError("challenge_failed")
    except httpx.InvalidURL:
        raise MCPCallbackError("connection_failed") from None
    except httpx.TimeoutException:
        raise MCPCallbackError("timeout") from None
    except httpx.DecodingError:
        raise MCPCallbackError("challenge_failed") from None
    except httpx.HTTPError as error:
        cause: BaseException | None = error
        while cause is not None:
            if isinstance(cause, ssl.SSLError):
                raise MCPCallbackError("tls_error") from None
            cause = cause.__cause__
        raise MCPCallbackError("connection_failed") from None
    except SSRFBlockedError:
        raise MCPCallbackError("connection_failed") from None
    except (ValueError, UnicodeDecodeError):
        raise MCPCallbackError("challenge_failed") from None
