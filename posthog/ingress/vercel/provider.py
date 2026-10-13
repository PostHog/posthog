"""Vercel Marketplace webhooks.

Three quirks: Vercel signs with HMAC-SHA1, its marketplace App is registered against the
secondary region rather than the primary one, and its invoice events are an open-ended family
that the registry, which matches an exact event type, sees under one collapsed name.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from posthog import regions
from posthog.ingress.contracts import ProviderSpec, WebhookDelivery
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.verify.schemes import HmacSignature, SignatureScheme

# Vercel names every invoice event `marketplace.invoice.<something>` and adds to the family over
# time. The registry matches an exact event type, so the family is registered under its prefix
# and the consumer reads the exact name off the payload.
VERCEL_BILLING_EVENT = "marketplace.invoice"
VERCEL_DEAUTHORIZATION_EVENT = "integration-configuration.removed"
VERCEL_EVENT_TYPES = frozenset({VERCEL_BILLING_EVENT, VERCEL_DEAUTHORIZATION_EVENT})

VERCEL_SIGNATURE_HEADER = "x-vercel-signature"

# Whether the request reached the region the marketplace App's one webhook URL names. Only that
# region forwards, so only there is a local miss somebody else's to settle; the consumer reads
# this to decide how loudly to report an installation it does not hold.
RECEIVING_REGION_CONTEXT_KEY = "is_receiving_region"

SPECS = (ProviderSpec(provider="vercel", app="marketplace", event_types=VERCEL_EVENT_TYPES),)


def _vercel_secret() -> str | None:
    return getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", "") or None


def delivery_event_type(raw_event_type: str) -> str:
    """The name the registry matches on, which collapses the invoice family to its prefix."""
    if raw_event_type.startswith(f"{VERCEL_BILLING_EVENT}."):
        return VERCEL_BILLING_EVENT
    return raw_event_type


class VercelProvider(WebhookProvider):
    provider = "vercel"
    app = "marketplace"
    invalid_signature_status = 401
    # The endpoint answered 401 for a missing secret as well as a bad signature, because the old
    # verifier could not tell the caller apart from the operator. Inherited rather than chosen.
    unconfigured_status = 401
    # A dropped secret makes every marketplace invoice answer 401, and the 401 above hides that
    # from anyone reading status codes, so it has to reach error tracking as the old view made it.
    reports_unconfigured = True
    # A delivery no consumer accepted answers 500, which is what this endpoint answered before.
    # Vercel publishes no retry policy, so whether that buys a redelivery is unknown; the status is
    # right either way, because the work did not run.
    retry_status = 500
    # The owning region waits up to 30 s for the billing service (`BillingManager
    # .handle_billing_provider_webhook`), so a shorter deadline here would make the receiving
    # region abandon an invoice the other region is still processing.
    forward_timeout_seconds = 35.0

    def __init__(self) -> None:
        self._scheme = HmacSignature(
            secret_getter=_vercel_secret,
            signature_header=VERCEL_SIGNATURE_HEADER,
            digest="sha1",
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def receiving_region_domain(self) -> str:
        # The marketplace App holds one webhook URL, on the secondary region, so deliveries arrive
        # there and the ones the primary region owns are forwarded on. A request that arrives on
        # any other host is reported as `ingress_delivery_host_matches_no_region`.
        return regions.SECONDARY_REGION_DOMAIN

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        in_receiving_region = request.get_host() == self.receiving_region_domain()
        # The whole body travels, not its `payload` field: the consumer needs the exact event
        # name the prefix above collapsed, and that lives on the envelope.
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                # Vercel does send one, as the body's `id`. It is left unused because turning
                # dedup on changes which redeliveries reach the consumer, and that belongs in its
                # own change rather than in a transport swap. Dedup stays the consumer's own job.
                delivery_id=None,
                event_type=delivery_event_type(str(payload.get("type", ""))),
                payload=payload,
                received_at=timezone.now(),
                context={RECEIVING_REGION_CONTEXT_KEY: "true" if in_receiving_region else "false"},
            ),
        )


def build_vercel_provider() -> VercelProvider:
    return VercelProvider()
