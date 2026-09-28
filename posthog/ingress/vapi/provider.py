"""Vapi voice-agent webhooks.

An unconfigured instance answers 503 and a bad signature 401, both of which the public
interview surface already relies on.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme
from posthog.rate_limit import VapiWebhookIPThrottle

VAPI_EVENT_TYPES = frozenset({"status-update", "end-of-call-report"})

# Vapi's HMAC-SHA256 hex digest is exactly 64 lowercase hex chars. Rejecting other shapes
# before the HMAC keeps casual probes off the digest path and out of the diagnostic logs.
VAPI_SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")

SPECS = (ProviderSpec(provider="vapi", app="default", event_types=VAPI_EVENT_TYPES),)


def _vapi_secret() -> str | None:
    return getattr(settings, "VAPI_WEBHOOK_SECRET", "") or None


class VapiProvider(WebhookProvider):
    provider = "vapi"
    app = "default"
    invalid_signature_status = 401
    unconfigured_status = 503
    # Vapi sends the delivery again after a 5xx, and its report is the only copy: nothing else
    # replays an interview. The consumer hands the report to a queue and does no other work, so a
    # consumer failure means the report reached no queue at all, and a receipt would drop it.
    retry_status = 500
    # The endpoint is public and unauthenticated, so the per-IP cap bounds how much
    # HMAC-verification CPU and structured-log volume one source can drive.
    throttle_class = VapiWebhookIPThrottle

    def __init__(self) -> None:
        self._scheme = HmacSha256(
            secret_getter=_vapi_secret,
            signature_header="X-Vapi-Signature",
            signature_pattern=VAPI_SIGNATURE_PATTERN,
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        message = payload.get("message")
        message = message if isinstance(message, Mapping) else {}
        call = message.get("call")
        call = call if isinstance(call, Mapping) else {}
        call_id = call.get("id")
        context = {"call_id": str(call_id)} if isinstance(call_id, str) and call_id else {}
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                # The call id is the only stable id Vapi sends, and it repeats across the
                # status update and the end-of-call report, so it cannot key dedup. The
                # consumer stays idempotent on it instead.
                delivery_id=None,
                event_type=str(message.get("type", "")),
                payload=payload,
                received_at=timezone.now(),
                context=context,
            ),
        )


def build_vapi_provider() -> VapiProvider:
    return VapiProvider()
