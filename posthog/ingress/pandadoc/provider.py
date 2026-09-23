"""PandaDoc document webhooks.

Two quirks: PandaDoc batches several events into one body, so one request becomes several
deliveries, and it may carry the signature as a query parameter instead of a header. A bad
signature answers 404 by design, so an attacker cannot tell a wrong secret from an unknown
route.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme, Verification, VerificationOutcome, header_value

PANDADOC_EVENT_TYPES = frozenset({"document_state_changed"})
PANDADOC_SIGNATURE_HEADER = "X-PandaDoc-Signature"

SPECS = (ProviderSpec(provider="pandadoc", app="default", event_types=PANDADOC_EVENT_TYPES),)


def _pandadoc_secret() -> str | None:
    return getattr(settings, "PANDADOC_WEBHOOK_SECRET", "") or None


class PandaDocProvider(WebhookProvider):
    provider = "pandadoc"
    app = "default"
    invalid_signature_status = 404
    # A missing secret answers like an unknown route too, so an operator mistake does not hand a
    # prober the "this endpoint exists" the 404 above exists to withhold.
    unconfigured_status = 404
    # A body naming the reason would hand back what the two 404s above withhold.
    explains_rejections = False
    # 500 is what this endpoint answered before it moved here, and PandaDoc redelivers after one,
    # so a signature the consumer failed to record is sent again instead of being lost.
    retry_status = 500

    def __init__(self, *, enabled: Callable[[], bool] | None = None) -> None:
        self._enabled = enabled
        self._scheme = HmacSha256(
            secret_getter=_pandadoc_secret,
            signature_header=PANDADOC_SIGNATURE_HEADER,
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def verify(self, request: HttpRequest) -> Verification:
        # A deployment that does not run the integration answers 404 before it reads anything off
        # the request, so the route stays indistinguishable from one that was never registered.
        if self._enabled is not None and not self._enabled():
            return Verification(outcome=VerificationOutcome.INVALID)
        # Read through the scheme's own case-insensitive lookup, because Django normalizes a
        # header name to title case and an exact-case match would never find this one.
        # Presence decides, not truthiness: an empty header is a signature that fails, never a
        # reason to go looking for a query parameter the caller did not sign with.
        if header_value(request.headers, PANDADOC_SIGNATURE_HEADER) is not None:
            return self._scheme.verify(body=request.body, headers=request.headers)
        # The query parameter is the fallback only, so a signed header always decides.
        return self._scheme.verify(
            body=request.body,
            headers={PANDADOC_SIGNATURE_HEADER: request.GET.get("signature", "")},
        )

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        events = payload if isinstance(payload, list) else [payload]
        received_at = timezone.now()
        deliveries: list[WebhookDelivery] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            deliveries.append(
                WebhookDelivery(
                    provider=self.provider,
                    app=self.app,
                    # PandaDoc sends no delivery id, so dedup is the consumer's own job.
                    delivery_id=None,
                    event_type=str(event.get("event", "")),
                    payload=event,
                    received_at=received_at,
                    context={},
                )
            )
        return tuple(deliveries)


def build_pandadoc_provider(*, enabled: Callable[[], bool] | None = None) -> PandaDocProvider:
    """Whether a deployment serves this endpoint at all is the endpoint owner's call, so it is
    passed in rather than decided here."""
    return PandaDocProvider(enabled=enabled)
