"""Per-delivery, per-consumer dedup marks in the Django cache."""

from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)

DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60


class DeliveryDedup:
    """Marks a (provider, consumer, delivery id) so a redelivery skips work already done.

    Keyed per consumer, not per delivery: one delivery legitimately fans out to several
    consumers, so a delivery-wide key would starve every consumer but the first. This sits
    alongside each consumer's own idempotency rather than replacing it.
    """

    @staticmethod
    def key(*, provider: str, consumer: str, delivery_id: str) -> str:
        return f"webhook_delivery:{provider}:{consumer}:{delivery_id}"

    def claim(self, *, provider: str, consumer: str, delivery_id: str) -> bool:
        """True when this process may run the consumer for this delivery.

        Fail-open on a cache error: dropping deliveries during a cache outage is worse than
        running a consumer twice, and consumers carry their own idempotency.
        """
        try:
            return bool(
                cache.add(
                    self.key(provider=provider, consumer=consumer, delivery_id=delivery_id),
                    True,
                    timeout=DELIVERY_DEDUP_TTL_SECONDS,
                )
            )
        except Exception:
            logger.warning(
                "ingress_dedup_cache_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )
            return True

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
