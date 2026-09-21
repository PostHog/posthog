"""The Vercel Marketplace webhook consumer.

`ee/` is not a product, so this module is named in `posthog.ingress.dispatch.loading` rather
than discovered. It stays cheap to import: the handling is behind a deferred import, because the
registry loads this module on the first delivery of any provider.
"""

import structlog

from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery
from posthog.ingress.vercel.provider import VERCEL_DEAUTHORIZATION_EVENT, VERCEL_EVENT_TYPES

logger = structlog.get_logger(__name__)


def _run_vercel_event(delivery: WebhookDelivery) -> None:
    from ee.api.vercel.webhook_events import (
        handle_vercel_event,  # noqa: PLC0415 - keeps billing and the license model off the registry's import path
    )

    body = dict(delivery.payload)
    outcome = handle_vercel_event(event_type=body.get("type"), payload=body.get("payload", {}))
    logger.info("vercel_webhook_handled", event_type=body.get("type"), outcome=str(outcome))


def _vercel_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the installation a deauthorization is about.

    Only deauthorization asks. A billing event for an installation this region does not hold is
    answered here rather than forwarded, which is what the endpoint did before.
    """
    if delivery.event_type != VERCEL_DEAUTHORIZATION_EVENT:
        return DeliveryOwnership.UNDECIDED

    from ee.api.vercel.webhook_events import extract_config_id, installation_is_local  # noqa: PLC0415 - as above

    config_id = extract_config_id(dict(delivery.payload).get("payload", {}))
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
