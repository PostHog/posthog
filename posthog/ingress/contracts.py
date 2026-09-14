"""The three values every lane in this package speaks in."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen


@frozen
class WebhookDelivery:
    """One inbound delivery, already verified and parsed.

    A provider incarnation may turn one HTTP request into several of these (PandaDoc
    batches events into one body), so this is the unit a consumer sees, not the request.
    """

    provider: str
    app: str
    delivery_id: str | None
    event_type: str
    payload: Mapping[str, Any]
    received_at: datetime
    context: Mapping[str, str]


@frozen
class WebhookConsumer:
    """A handler a product registers for some of a provider app's event types.

    ``name`` is part of the dedup cache key, so renaming one lets a redelivery run twice.
    The handler's return value is ignored: the HTTP response is a transport receipt the
    provider incarnation decides.
    """

    name: str
    provider: str
    app: str
    event_types: frozenset[str]
    handler: Callable[[WebhookDelivery], None]
    # Off for a consumer that already keys its own recovery on the provider's delivery id: the
    # 24 h mark would otherwise stop a redelivery from ever reaching that recovery path.
    dedup: bool = True


@frozen
class ProviderSpec:
    """What one provider app accepts, as the registry validates consumers against it."""

    provider: str
    app: str
    event_types: frozenset[str]
