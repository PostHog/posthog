# Test cases for inbound-webhooks-go-through-ingress rule.
# ruff: noqa: F841, E501
import hmac
import hashlib

from collections.abc import Callable

import stripe
from django.http import HttpRequest, HttpResponse

from posthog.ingress.github import build_github_provider
from posthog.ingress.views import build_webhook_view


def _verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    # ruleid: inbound-webhooks-go-through-ingress
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    # ruleid: inbound-webhooks-go-through-ingress
    return hmac.compare_digest(expected, signature)


def hand_rolled_view(request: HttpRequest) -> HttpResponse:
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_signature(request.body, signature, "secret"):
        return HttpResponse(status=403)
    return HttpResponse(status=202)


def verify_vapi_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    # ruleid: inbound-webhooks-go-through-ingress
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # ruleid: inbound-webhooks-go-through-ingress
    return hmac.compare_digest(expected, signature)


def signature_ok(body: bytes, signature: str, secret: str) -> bool:
    # ruleid: inbound-webhooks-go-through-ingress
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # ruleid: inbound-webhooks-go-through-ingress
    return hmac.compare_digest(expected, signature)


def _is_valid_signature(body: bytes, signature: str, secret: str) -> bool:
    # ruleid: inbound-webhooks-go-through-ingress
    expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    # ruleid: inbound-webhooks-go-through-ingress
    return hmac.compare_digest(expected, signature)


def bracket_header_view(request: HttpRequest) -> HttpResponse:
    signature = request.headers["X-Slack-Signature"]
    expected = hmac.new(b"secret", request.body, hashlib.sha256).hexdigest()
    # ruleid: inbound-webhooks-go-through-ingress
    if not hmac.compare_digest(expected, signature):
        return HttpResponse(status=403)
    return HttpResponse(status=202)


def sdk_delegated_view(request: HttpRequest) -> HttpResponse:
    # ruleid: inbound-webhooks-go-through-ingress
    stripe.WebhookSignature.verify_header(request.body.decode(), "t=1,v1=abc", "secret", tolerance=300)
    return HttpResponse(status=202)


def ok_through_ingress() -> Callable[[HttpRequest], HttpResponse]:
    # ok: inbound-webhooks-go-through-ingress
    return build_webhook_view(build_github_provider("posthog"))


def ok_outbound_signing(body: bytes, secret: str) -> str:
    # ok: inbound-webhooks-go-through-ingress
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_test_signature(body: bytes, secret: str) -> dict[str, str]:
    # ok: inbound-webhooks-go-through-ingress
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    # ok: inbound-webhooks-go-through-ingress
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(f"{timestamp}.".encode())
    mac.update(body)
    return mac.digest().hex()
