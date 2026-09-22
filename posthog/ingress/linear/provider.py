"""Linear OAuth application webhooks.

Linear creates one webhook per workspace that authorizes the PostHog OAuth app. Each webhook
uses the OAuth application's single signing secret, so one secret serves every workspace, like
a GitHub App.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme
from posthog.models.instance_setting import get_instance_setting

LINEAR_EVENT_TYPES = frozenset({"Issue", "Comment"})

SPECS = (ProviderSpec(provider="linear", app="default", event_types=LINEAR_EVENT_TYPES),)


def _linear_secret() -> str | None:
    secret = get_instance_setting("LINEAR_WEBHOOK_SECRET")
    return secret if secret else None


class LinearProvider(WebhookProvider):
    provider = "linear"
    app = "default"
    # Linear retries a delivery up to three times on a non-200 response, after one minute, one hour
    # and six hours, so a delivery no consumer accepted is worth asking for again.
    retry_status = 500

    def __init__(self) -> None:
        self._scheme = HmacSha256(
            secret_getter=_linear_secret,
            signature_header="Linear-Signature",
            signature_pattern=re.compile(r"^[0-9a-f]{64}$"),
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        organization_id = payload.get("organizationId")
        context = (
            {"organization_id": str(organization_id)} if isinstance(organization_id, str) and organization_id else {}
        )
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=request.headers.get("Linear-Delivery"),
                event_type=request.headers.get("Linear-Event", ""),
                payload=payload,
                received_at=timezone.now(),
                context=context,
            ),
        )


def build_linear_provider() -> LinearProvider:
    return LinearProvider()
