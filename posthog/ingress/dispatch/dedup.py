"""Per-delivery, per-consumer dedup marks in the Django cache."""

from enum import Enum
from uuid import uuid4

from django.core.cache import caches
from django.core.cache.backends.base import BaseCache

import structlog

from posthog.dataclasses import frozen
from posthog.ingress.dispatch.budget import delivery_budget_seconds

logger = structlog.get_logger(__name__)

# A cache alias with one client on the Redis primary. The default alias is replica aware when
# REDIS_READER_URL is set, and the fence in `release()` needs the read and the delete to see the
# same Redis.
INGRESS_DEDUP_CACHE_ALIAS = "ingress_dedup"

DELIVERY_DEDUP_TTL_SECONDS = 24 * 60 * 60

# What the lease adds to the request's delivery budget. The budget is checked between consumers
# and never inside one, so a consumer that starts just under the deadline overruns it, and the
# margin has to cover that overrun plus the rest of the request. A minute is long enough that a
# slow run keeps its claim, and short enough that a claim nobody settled costs one redelivery
# rather than the provider's whole retry window.
DELIVERY_CLAIM_LEASE_MARGIN_SECONDS = 60

_IN_PROGRESS = "in_progress"
_DONE = "done"


def _holder_key(key: str) -> str:
    """The key that names the run holding the lease.

    The token sits beside the mark instead of inside it so that the mark keeps the exact value
    the previous version wrote. During a rolling deploy, a worker on that version reads any other
    value as done and receipts the delivery, which stops the provider retrying a delivery the new
    worker can still fail.
    """
    return f"{key}:holder"


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


@frozen
class DeliveryClaimResult:
    """What the claim answered, and the token that names the run holding the mark.

    The token is what lets `release()` tell its own claim from a newer run's. It is None when no
    run holds the mark on this run's behalf, which is every state but `CLAIMED`, plus a `CLAIMED`
    that the cache failed open on.
    """

    state: DeliveryClaim
    token: str | None = None


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

    Because two runs can overlap, a second key names the run that holds the mark. A run that lost
    its lease settles the mark to done, which stays true, but it cannot delete the claim or the
    done mark another run wrote in the meantime.
    """

    @staticmethod
    def key(*, provider: str, consumer: str, delivery_id: str) -> str:
        return f"webhook_delivery:{provider}:{consumer}:{delivery_id}"

    @property
    def cache(self) -> BaseCache:
        """Looked up per call, so overriding CACHES in a test reaches this."""
        return caches[INGRESS_DEDUP_CACHE_ALIAS]

    def claim(self, *, provider: str, consumer: str, delivery_id: str) -> DeliveryClaimResult:
        """Take the mark for this consumer, or say what state the holder left it in.

        Fail-open on a cache error: dropping deliveries during a cache outage is worse than
        running a consumer twice, and consumers carry their own idempotency.
        """
        key = self.key(provider=provider, consumer=consumer, delivery_id=delivery_id)
        token = uuid4().hex
        lease_seconds = delivery_claim_lease_seconds()
        cache = self.cache
        try:
            for _ in range(2):
                if cache.add(key, _IN_PROGRESS, timeout=lease_seconds):
                    # The mark's add picks the winner on its own; the holder key only names it. A
                    # process that dies between the two writes leaves a lease that nobody can
                    # release and that runs out on the lease timeout.
                    cache.set(_holder_key(key), token, timeout=lease_seconds)
                    return DeliveryClaimResult(state=DeliveryClaim.CLAIMED, token=token)
                held = cache.get(key)
                if held is None:
                    # The lease ran out between the add and this read, so nobody holds the mark
                    # now. Take it instead: a lease that ran out is a run that never settled, and
                    # reading the gap as done would receipt work that did not finish.
                    continue
                # Anything that is not the in-progress value counts as done. That covers a mark
                # written before this state existed, which keeps the receipt those marks earned
                # before.
                return DeliveryClaimResult(
                    state=DeliveryClaim.IN_PROGRESS if held == _IN_PROGRESS else DeliveryClaim.DONE
                )
        except Exception:
            logger.warning(
                "ingress_dedup_cache_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )
            return DeliveryClaimResult(state=DeliveryClaim.CLAIMED)
        # Two leases ran out under this claim, so runs keep starting and never settling. Answer
        # in progress, which costs the delivery its receipt and has the provider send it again,
        # rather than claiming a mark this run cannot keep.
        return DeliveryClaimResult(state=DeliveryClaim.IN_PROGRESS)

    def complete(self, *, provider: str, consumer: str, delivery_id: str) -> None:
        """Settle the mark once the consumer returned, so a redelivery reads it as done.

        This resets the remaining time to the full TTL, because the cache does not report what
        is left. A redelivery is deduped for 24 hours from when the work finished.

        The write is not fenced on the holder token, unlike `release()`. Done is a fact about the
        delivery rather than about who holds the key: this consumer ran the delivery and returned,
        so the mark is true whoever wrote the value it replaces. Fencing it would instead drop the
        mark of a run that outlived its lease, and let the provider redeliver finished work.
        """
        try:
            self.cache.set(
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

    def release(self, *, provider: str, consumer: str, delivery_id: str, token: str | None) -> None:
        """Drop this run's own mark after the consumer raised, so a redelivery reaches it.

        The mark is set before the consumer runs, so without this a failure would burn the
        delivery for the whole TTL.

        Only this run's own mark, because the lease can run out while the consumer still runs. By
        then the key can carry a newer run's claim, which a delete would turn into a third run, or
        the done mark of a run that finished, which a delete would hand back to the provider as
        work to redeliver. So a delete needs the holder key to name this run and the mark to still
        be a lease. The holder key alone is not enough, because settling does not clear it, and
        this run would drop the done mark another run wrote while this one held the lease.

        The cache API has no compare-and-delete, so the read and the delete are two calls and a
        newer claim written between them is still deleted. That window is microseconds wide, and
        running a consumer twice is the exposure this mark only narrows: consumers are required to
        be idempotent underneath it.
        """
        if token is None:
            return
        key = self.key(provider=provider, consumer=consumer, delivery_id=delivery_id)
        holder_key = _holder_key(key)
        cache = self.cache
        try:
            held = cache.get_many([key, holder_key])
            if held.get(holder_key) != token or held.get(key) != _IN_PROGRESS:
                return
            cache.delete_many([key, holder_key])
        except Exception:
            logger.warning(
                "ingress_dedup_release_failed",
                provider=provider,
                consumer=consumer,
                delivery_id=delivery_id,
                exc_info=True,
            )
