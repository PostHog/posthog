"""Per-delivery, per-consumer dedup marks in the Django cache."""

from enum import Enum

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60

_IN_PROGRESS = "in_progress"
_DONE = "done"


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
            if cache.add(key, _IN_PROGRESS, timeout=DELIVERY_DEDUP_TTL_SECONDS):
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
