"""The three values every lane in this package speaks in."""

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Any

from posthog.dataclasses import frozen


class DeliveryOwnership(Enum):
    """Where the resource a delivery is about lives, as the consumer that owns it sees it."""

    LOCAL = "local"  # this region holds the resource; dispatch here
    ELSEWHERE = "elsewhere"  # the resource lives in the other region; forward the request
    UNDECIDED = "undecided"  # nothing in the delivery says; dispatch here, forward nothing
    # The lookup raised, so it ruled no region out. A consumer never answers this one: the
    # dispatcher records it, and the transport asks a provider that redelivers to send again.
    FAILED = "failed"


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
    # A consumer whose resources are split by region answers where this delivery's resource lives,
    # and ingress forwards the signed request when the answer is elsewhere. A lookup inside must be
    # bounded (`bounded_statement_timeout`): it runs in the request, before dispatch. Let a
    # transient error out rather than answering local, undecided or elsewhere through it: a raised
    # lookup asks a provider that redelivers for the delivery again, a guess loses the delivery,
    # and an elsewhere guess also sends its contents to a region that may not own them.
    ownership: Callable[[WebhookDelivery], DeliveryOwnership] | None = None


@frozen
class ProviderSpec:
    """What one provider app accepts, as the registry validates consumers against it."""

    provider: str
    app: str
    event_types: frozenset[str]


@frozen
class DeliveryOwnershipAnswers:
    """What the consumers that declare an ownership lookup said about one delivery.

    The two names carry different decisions. `elsewhere_consumers` forwards the signed request to
    the other region. `failed_consumers` says a lookup did not answer, which leaves the owning
    region unknown, so a provider that redelivers is asked for the delivery again.
    """

    elsewhere_consumers: tuple[str, ...] = ()
    failed_consumers: tuple[str, ...] = ()


@frozen
class DeliveryDispatch:
    """What the dispatcher can vouch for after one delivery's consumers ran.

    A consumer that raised or that the budget skipped is named here; a deduped one is not,
    because the earlier delivery accepted it. A delivery with nothing to run accepts by
    construction, so the names are empty and the transport keeps its receipt.
    """

    unaccepted_consumers: tuple[str, ...] = ()
