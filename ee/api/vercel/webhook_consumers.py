"""The Vercel Marketplace webhook consumer.

`ee/` is not a product, so this module is named in `posthog.ingress.dispatch.loading` rather
than discovered. It stays cheap to import: the handling is behind a deferred import, because the
registry loads this module on the first delivery of any provider.
"""

from typing import Any

import structlog

from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery
from posthog.ingress.vercel.provider import RECEIVING_REGION_CONTEXT_KEY, VERCEL_EVENT_TYPES

logger = structlog.get_logger(__name__)


def _event_payload(delivery: WebhookDelivery) -> dict[str, Any]:
    """The `payload` field of the Vercel envelope the provider passed through whole."""
    payload = dict(delivery.payload).get("payload")
    return payload if isinstance(payload, dict) else {}


def _in_receiving_region(delivery: WebhookDelivery) -> bool:
    return delivery.context.get(RECEIVING_REGION_CONTEXT_KEY) == "true"


def _run_vercel_event(delivery: WebhookDelivery) -> None:
    from ee.api.vercel.webhook_events import (
        handle_vercel_event,  # noqa: PLC0415 - keeps billing and the license model off the registry's import path
    )

    event_type = dict(delivery.payload).get("type")
    outcome = handle_vercel_event(
        event_type=event_type,
        payload=_event_payload(delivery),
        in_receiving_region=_in_receiving_region(delivery),
    )
    logger.info("vercel_webhook_handled", event_type=event_type, outcome=str(outcome))


def _vercel_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the installation this event is about.

    Both event families ask, because both are processed by the region that holds the
    installation: only there does `BillingManager` find the `Organization` a billing call needs,
    and only there is there an installation to delete.
    """
    from ee.api.vercel.webhook_events import extract_config_id, installation_is_local  # noqa: PLC0415 - as above

    config_id = extract_config_id(_event_payload(delivery))
    if not config_id:
        return DeliveryOwnership.UNDECIDED
    return DeliveryOwnership.LOCAL if installation_is_local(config_id) else DeliveryOwnership.ELSEWHERE


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="vercel_marketplace",
        provider="vercel",
        app="marketplace",
        event_types=VERCEL_EVENT_TYPES,
        handler=_run_vercel_event,
        ownership=_vercel_ownership,
    ),
)
