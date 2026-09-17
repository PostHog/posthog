"""Per-delivery, per-consumer dedup marks in the Django cache."""

from enum import Enum

from django.core.cache import cache

import structlog

from posthog.ingress.dispatch.budget import delivery_budget_seconds

logger = structlog.get_logger(__name__)

DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60

# What the lease adds to the request's delivery budget. The budget is checked between consumers
# and never inside one, so a consumer that starts just under the deadline overruns it, and the
# margin has to cover that overrun plus the rest of the request. A minute is long enough that a
# slow run keeps its claim, and short enough that a claim nobody settled costs one redelivery
# rather than the provider's whole retry window.
DELIVERY_CLAIM_LEASE_MARGIN_SECONDS = 60

_IN_PROGRESS = "in_progress"
_DONE = "done"


def delivery_claim_lease_seconds() -> float:
    """How long an unsettled claim keeps a redelivery out.

    Read per claim, like the budget it is built on, so tuning the budget live carries into the
    lease.
    """
    return delivery_budget_seconds() + DELIVERY_CLAIM_LEASE_MARGIN_SECONDS


class DeliveryClaim(Enum):
    """What the mark says about this consumer's work on this delivery."""

    CLAIMED = "claimed"  # nothing held the mark, so this run does the work
    IN_PROGRESS = "in_progress"  # another run holds the mark and has not settled yet
    DONE = "done"  # an earlier run finished the work


class DeliveryDedup:
    """Marks a (provider, consumer, delivery id) so a redelivery skips work already done.

    Keyed per consumer, not per delivery: one delivery legitimately fans out to several
    consumers, so a delivery-wide key would starve every consumer but the first. This sits
    alongside each consumer's own idempotency rather than replacing it.

    The mark carries a state because it is written before the handler runs. Without one, a
    redelivery that arrives while the first run is still going reads the mark as work already
    done and earns a receipt, which stops the provider from retrying a delivery the first run
    can still fail.

    The in-progress mark is a lease, not a fact. The process holding it can die before it settles,
    on a deploy or an OOM kill, and nothing settles it afterwards. A provider that redelivers reads
    an unsettled mark as in flight and is answered a retry status, so a mark that outlived its run
    would refuse every redelivery until the provider gave up and the delivery was lost. The lease
    therefore runs out on its own after `delivery_claim_lease_seconds()`, which means a redelivery
    can run beside a first attempt that overran the budget. That is the exposure a provider without
    dedup has on every retry, and consumers are required to be idempotent underneath this.
    """

    @staticmethod
    def key(*, provider: str, consumer: str, delivery_id: str) -> str:
        return f"webhook_delivery:{provider}:{consumer}:{delivery_id}"

    def claim(self, *, provider: str, consumer: str, delivery_id: str) -> DeliveryClaim:
        """Take the mark for this consumer, or say what state the holder left it in.

        Fail-open on a cache error: dropping deliveries during a cache outage is worse than
        running a consumer twice, and consumers carry their own idempotency.
        """
        key = self.key(provider=provider, consumer=consumer, delivery_id=delivery_id)
        try:
            if cache.add(key, _IN_PROGRESS, timeout=delivery_claim_lease_seconds()):
                return DeliveryClaim.CLAIMED
            held = cache.get(key)
        except Exception:
            logger.warning(
                "ingress_dedup_cache_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )
            return DeliveryClaim.CLAIMED
        # Anything but the in-progress value counts as done. That covers a mark written before
        # this state existed, and a key that expired between the add and this read. Both mean
        # the delivery keeps its receipt, which is what those marks did before.
        return DeliveryClaim.IN_PROGRESS if held == _IN_PROGRESS else DeliveryClaim.DONE

    def complete(self, *, provider: str, consumer: str, delivery_id: str) -> None:
        """Settle the mark once the consumer returned, so a redelivery reads it as done.

        This resets the remaining time to the full TTL, because the cache does not report what
        is left. A redelivery is deduped for 24 hours from when the work finished.
        """
        try:
            cache.set(
                self.key(provider=provider, consumer=consumer, delivery_id=delivery_id),
                _DONE,
                timeout=DELIVERY_DEDUP_TTL_SECONDS,
            )
        except Exception:
            logger.warning(
                "ingress_dedup_complete_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )

    def release(self, *, provider: str, consumer: str, delivery_id: str) -> None:
        """Drop the mark after a consumer raised, so the provider's redelivery reaches it.

        The mark is set before the consumer runs, so without this a failure would burn the
        delivery for the whole TTL.
        """
        try:
            cache.delete(self.key(provider=provider, consumer=consumer, delivery_id=delivery_id))
        except Exception:
            logger.warning(
                "ingress_dedup_release_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )
