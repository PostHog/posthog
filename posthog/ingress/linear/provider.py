"""Linear OAuth App deliveries.

Linear creates one webhook per workspace that authorizes the PostHog Linear App, and every one of
them posts to the URL in the App's webhook settings, signed with the App's one signing secret.
"""

import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import InvalidPayload, WebhookProvider, require_known_app
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme

LINEAR_EVENT_TYPES = frozenset({"Issue"})

LINEAR_SIGNATURE_HEADER = "Linear-Signature"

# Linear recommends that a receiver refuses a body sent more than a minute before it arrives.
_MAX_TIMESTAMP_SKEW_SECONDS = 60

SPECS = (ProviderSpec(provider="linear", app="posthog", event_types=LINEAR_EVENT_TYPES),)


# An inbound signing secret stays off the credentials service, because every deployment that holds
# a caller key can read any entry there. It is a plain env var on the pods that check it.
def _posthog_app_secret() -> str | None:
    return getattr(settings, "LINEAR_APP_WEBHOOK_SECRET", "") or None


def _timestamp_is_fresh(payload: Mapping[str, Any]) -> bool:
    timestamp_ms = payload.get("webhookTimestamp")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int | float):
        return False
    return abs(time.time() - timestamp_ms / 1000) <= _MAX_TIMESTAMP_SKEW_SECONDS


class LinearProvider(WebhookProvider):
    provider = "linear"
    # Linear counts only a 200 as delivered. It retries anything else and can disable a webhook
    # that keeps failing, so the default 202 receipt would look like an outage to Linear.
    success_status = 200
    # Linear redelivers after a non-200 (after 1 minute, 1 hour and 6 hours), so a delivery that
    # ingress cannot vouch for asks for that retry instead of being receipted and lost.
    retry_status = 500
    # A self-hosted deployment may never set up the Linear App, so a missing secret must not
    # answer a server error to every anonymous probe of the public URL.
    unconfigured_status = 403
    # The body must not tell an unauthenticated caller that the endpoint is unconfigured, which is
    # an operator fact about an instance anyone can probe.
    explains_rejections = False

    def __init__(self, app: str) -> None:
        require_known_app(self.provider, app, SPECS)
        self.app = app
        self._scheme = HmacSha256(
            secret_getter=_posthog_app_secret,
            signature_header=LINEAR_SIGNATURE_HEADER,
            signature_pattern=re.compile(r"^[0-9a-f]{64}$"),
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        # One-off: Linear puts its replay timestamp inside the signed body, not in a signed
        # header, so the scheme cannot check it. The `Linear-Timestamp` header carries the same
        # value but is not covered by the signature, so it proves nothing.
        if not _timestamp_is_fresh(payload):
            raise InvalidPayload("webhookTimestamp is missing or outside the replay window")
        organization_id = payload.get("organizationId")
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=request.headers.get("Linear-Delivery") or None,
                event_type=request.headers.get("Linear-Event", ""),
                payload=payload,
                received_at=timezone.now(),
                context={"organization_id": organization_id} if isinstance(organization_id, str) else {},
            ),
        )


def build_linear_provider(app: str) -> LinearProvider:
    return LinearProvider(app)
